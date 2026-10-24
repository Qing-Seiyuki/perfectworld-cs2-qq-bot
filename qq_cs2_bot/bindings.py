"""Group-scoped bindings and report preferences."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import uuid

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.sqlite3"


def valid_steam_id(value: str) -> bool:
    if not re.fullmatch(r"[0-9]{17}", value):
        return False
    number = int(value)
    # Public-universe, individual account, desktop instance; not ownership proof.
    return (number >> 56 == 1 and (number >> 52) & 15 == 1
            and (number >> 32) & 0xFFFFF == 1 and number & 0xFFFFFFFF != 0)


class BindingStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4):
                raise ValueError("绑定数据库版本不兼容")
            db.execute("""CREATE TABLE IF NOT EXISTS bindings (
                app TEXT NOT NULL, group_id TEXT NOT NULL, member TEXT NOT NULL,
                request_id TEXT NOT NULL UNIQUE, steam_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','verified')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                verified_at TEXT,
                PRIMARY KEY(app, group_id, member))""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS verified_game_owner
                ON bindings(app, group_id, steam_id) WHERE status='verified'""")
            db.execute("""CREATE TABLE IF NOT EXISTS binding_events (
                app TEXT NOT NULL, group_id TEXT NOT NULL, message_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(app, group_id, message_id))""")
            if version < 2:
                for definition in ("display_name TEXT", "challenge TEXT", "challenge_expires INTEGER", "last_check INTEGER"):
                    db.execute("ALTER TABLE bindings ADD COLUMN " + definition)
            db.execute("""CREATE TABLE IF NOT EXISTS member_settings (
                app TEXT NOT NULL, group_id TEXT NOT NULL, member TEXT NOT NULL,
                report_opt_in INTEGER NOT NULL DEFAULT 0 CHECK(report_opt_in IN (0,1)),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(app, group_id, member))""")
            db.execute("""CREATE TABLE IF NOT EXISTS group_settings (
                app TEXT NOT NULL, group_id TEXT NOT NULL,
                report_enabled INTEGER NOT NULL DEFAULT 0 CHECK(report_enabled IN (0,1)),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(app, group_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS report_deliveries (
                app TEXT NOT NULL, group_id TEXT NOT NULL, match_id TEXT NOT NULL,
                report_type TEXT NOT NULL DEFAULT 'team',
                target_steam_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('ready','sending','sent','unknown')),
                qq_message_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(app, group_id, match_id, report_type))""")
            db.execute("PRAGMA user_version=4")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def command(self, app: str, group: str, member: str, message: str, text: str) -> str | None:
        """None means unrecognized or duplicate. Identity comes from QQ event only."""
        parts = text.strip().removeprefix("#").split()
        if not parts or parts[0] not in ("绑定", "我的绑定", "解绑", "验证绑定", "称呼", "播报", "个人播报", "群播报"):
            return None
        if not all(isinstance(x, str) and x for x in (app, group, member, message)):
            raise ValueError("QQ 事件缺少可信身份标识")
        with self.transaction() as db:
            db.execute("DELETE FROM binding_events WHERE created_at < datetime('now', '-7 days')")
            claimed = db.execute("INSERT OR IGNORE INTO binding_events(app,group_id,message_id) VALUES(?,?,?)",
                                 (app, group, message))
            if not claimed.rowcount:
                return None
            identity = (app, group, member)
            row = db.execute("SELECT * FROM bindings WHERE app=? AND group_id=? AND member=?", identity).fetchone()
            if parts[0] == "我的绑定":
                if len(parts) != 1:
                    return "请发送：我的绑定（仅查看自己在本群的关联）。"
                if row is None:
                    return "你在本群尚未绑定。请发送：绑定 你的SteamID64"
                label = "已验证" if row["status"] == "verified" else "待验证"
                return f"本群绑定：{label}\nSteamID：{row['steam_id']}\n群内称呼（自设）：{row['display_name'] or '未设置'}\n申请编号：{row['request_id']}\n发送“播报 状态”查看自动战报开关。"
            if parts[0] == "群播报":
                if len(parts) != 2 or parts[1] not in ("开", "关", "状态"):
                    return "群总开关仅由机器人维护者在运行电脑上设置；可发送：群播报 状态。"
                group_state = db.execute("SELECT report_enabled FROM group_settings WHERE app=? AND group_id=?", (app, group)).fetchone()
                group_on = bool(group_state and group_state[0])
                if parts[1] == "状态":
                    return f"本群自动播报总开关：{'开' if group_on else '关'}（影响全群，由维护者设置）。"
                return "群总开关不能通过群消息修改；请联系机器人维护者。你的个人订阅不会因此改变。"
            if parts[0] in ("播报", "个人播报"):
                if len(parts) != 2 or parts[1] not in ("开", "关", "状态"):
                    return "请发送：个人播报 开、个人播报 关，或播报 状态。"
                group_state = db.execute("SELECT report_enabled FROM group_settings WHERE app=? AND group_id=?", (app, group)).fetchone()
                member_state = db.execute("SELECT report_opt_in FROM member_settings WHERE app=? AND group_id=? AND member=?", identity).fetchone()
                group_on = bool(group_state and group_state[0])
                member_on = bool(member_state and member_state[0])
                if parts[1] == "状态":
                    verified = bool(row and row["status"] == "verified")
                    return (f"我的比赛自动播报：{'开' if member_on else '关'}（只影响我的比赛）\n"
                            f"本群自动播报总开关：{'开' if group_on else '关'}（影响全群，由维护者设置）\n"
                            f"绑定：{'已验证' if verified else '未验证'}。\n"
                            "只有个人订阅和群总开关都开启，才会播报你的新比赛。")
                if parts[1] == "开" and (not row or row["status"] != "verified"):
                    return "请先完成账号绑定验证，再开启个人播报。"
                enabled = int(parts[1] == "开")
                db.execute("""INSERT INTO member_settings(app,group_id,member,report_opt_in)
                    VALUES(?,?,?,?) ON CONFLICT(app,group_id,member) DO UPDATE SET
                    report_opt_in=excluded.report_opt_in,updated_at=CURRENT_TIMESTAMP""", (*identity, enabled))
                return (f"你的个人比赛订阅已设为：{'开' if enabled else '关'}；"
                        f"本群总开关仍为：{'开' if group_on else '关'}（未更改）。"
                        "群总开关由维护者单独设置。")
            if parts[0] == "称呼":
                if row is None:
                    return "请先申请绑定，再设置群内称呼。"
                name = " ".join(parts[1:])
                if not 1 <= len(name) <= 24 or any(c in name for c in "<>[]\r\n") or any(ord(c) < 32 for c in name):
                    return "格式：称呼 你的群内昵称（1～24字，不含尖括号或方括号）。"
                db.execute("UPDATE bindings SET display_name=? WHERE app=? AND group_id=? AND member=?", (name, *identity))
                return f"群内称呼已设为：{name}。账号验证通过后会用于本群战报；这是自行设置的称呼。"
            if parts[0] == "验证绑定":
                if len(parts) != 1:
                    return "请发送：验证绑定"
                if row is None:
                    return "请先发送：绑定 你的SteamID64"
                if row["status"] == "verified":
                    return "你的绑定已验证，无需再次验证。"
                return ("请向机器人维护者索取验证链接；如本条消息末尾附有链接，可直接使用。"
                        "仅发送 SteamID 不能证明账号归属。")
            if parts[0] == "解绑":
                if len(parts) != 1:
                    return "请发送：解绑（仅解除自己在本群的关联）。"
                db.execute("DELETE FROM bindings WHERE app=? AND group_id=? AND member=?", identity)
                db.execute("DELETE FROM member_settings WHERE app=? AND group_id=? AND member=?", identity)
                return "已解除你在本群的账号关联并删除该绑定记录；其他群不受影响。" if row else "你在本群尚未绑定，无需解绑。"
            if len(parts) != 2 or not valid_steam_id(parts[1]):
                return "格式：绑定 17位SteamID64。请使用个人 Steam 账号 ID，不是昵称或比赛 ID。"
            steam_id = parts[1]
            if row:
                if row["steam_id"] != steam_id:
                    return "你在本群已有绑定或待验证申请。更换账号前请先发送“解绑”。"
                return ("该账号已验证绑定。" if row["status"] == "verified" else
                        f"该账号已有待验证申请。申请编号：{row['request_id']}\n"
                        "发送“#绑定链接 你的申请编号”以获得绑定链接。")
            owner = db.execute("SELECT 1 FROM bindings WHERE app=? AND group_id=? AND steam_id=? AND status='verified'",
                               (app, group, steam_id)).fetchone()
            if owner:
                return "此 Steam 账号在本群已有已验证绑定，请联系机器人维护者核对。"
            request_id = uuid.uuid4().hex
            db.execute("INSERT INTO bindings(app,group_id,member,request_id,steam_id,status) VALUES(?,?,?,?,?,'pending')",
                       (*identity, request_id, steam_id))
            return (f"已记录绑定申请（待验证）。\nSteamID：{steam_id}\n申请编号：{request_id}\n"
                    "请向机器人维护者索取 Steam 验证链接；如消息末尾附有链接，可直接使用。"
                    "不要向群里发送密码或登录令牌。\n"
                    "可发送“我的绑定”查看，或“解绑”取消。验证后可发送“播报 开”。\n"
                    "发送“#绑定链接 你的申请编号”以获得绑定链接。")

    def approve(self, request_id: str, steam_id: str) -> None:
        """Operator must independently check ownership; IDs alone aren't evidence."""
        with self.transaction() as db:
            row = db.execute("SELECT * FROM bindings WHERE request_id=? AND steam_id=?", (request_id, steam_id)).fetchone()
            if row is None:
                raise ValueError("申请不存在或账号不一致；请重新核对当前申请")
            try:
                db.execute("UPDATE bindings SET status='verified', verified_at=CURRENT_TIMESTAMP, challenge=NULL, challenge_expires=NULL, last_check=NULL WHERE request_id=? AND status='pending'",
                           (request_id,))
            except sqlite3.IntegrityError:
                raise ValueError("此账号在同一群已有已验证绑定") from None

    def get_binding(self, app: str, group: str, member: str) -> dict | None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM bindings WHERE app=? AND group_id=? AND member=?", (app, group, member)).fetchone()
            return dict(row) if row else None

    def claim_event(self, app: str, group: str, message: str) -> bool:
        with self.transaction() as db:
            db.execute("DELETE FROM binding_events WHERE created_at < datetime('now', '-7 days')")
            return bool(db.execute("INSERT OR IGNORE INTO binding_events(app,group_id,message_id) VALUES(?,?,?)", (app, group, message)).rowcount)

    def labels(self, app: str, group: str) -> dict[str, str]:
        with self.transaction() as db:
            rows = db.execute("SELECT steam_id,display_name FROM bindings WHERE app=? AND group_id=? AND status='verified'", (app, group))
            return {row["steam_id"]: row["display_name"] or "已绑定（未设置称呼）" for row in rows}

    def set_group_report_enabled(self, app: str, group: str, enabled: bool) -> None:
        """Local operator action only; QQ group messages cannot call this."""
        if not app or not group:
            raise ValueError("应用和群标识不能为空")
        with self.transaction() as db:
            db.execute("""INSERT INTO group_settings(app,group_id,report_enabled) VALUES(?,?,?)
                ON CONFLICT(app,group_id) DO UPDATE SET
                report_enabled=excluded.report_enabled,updated_at=CURRENT_TIMESTAMP""", (app, group, int(enabled)))

    def eligible_members(self, app: str, group: str) -> list[dict]:
        """Future monitor uses this gate; both opt-ins must be enabled."""
        with self.transaction() as db:
            rows = db.execute("""SELECT b.member,b.steam_id,b.display_name FROM bindings AS b
                JOIN member_settings AS m ON m.app=b.app AND m.group_id=b.group_id AND m.member=b.member
                JOIN group_settings AS g ON g.app=b.app AND g.group_id=b.group_id
                WHERE b.app=? AND b.group_id=? AND b.status='verified'
                  AND m.report_opt_in=1 AND g.report_enabled=1""", (app, group)).fetchall()
            return [dict(row) for row in rows]



def main():
    parser = argparse.ArgumentParser(description="本机人工确认绑定；须事先独立核对账号归属")
    parser.add_argument("--approve", required=True, help="群内返回的申请编号")
    parser.add_argument("--steam-id", required=True)
    parser.add_argument("--ownership-checked", action="store_true", help="声明已人工核对 QQ 用户与 Steam 账号归属")
    args = parser.parse_args()
    if not args.ownership_checked:
        parser.error("须先独立核对账号归属，再使用 --ownership-checked；仅知道 SteamID 不算验证")
    try:
        BindingStore().approve(args.approve, args.steam_id)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"确认失败：{error}\n")
    print("绑定已人工确认；可在原群发送“我的绑定”或“播报 状态”查看。")


if __name__ == "__main__":
    main()
