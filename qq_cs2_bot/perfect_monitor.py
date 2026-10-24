"""Poll verified Perfect World players and publish new completed team reports."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
import re
import sqlite3
import time
from pathlib import Path

from .bindings import BindingStore
from .monitor_core import prepare_team_report
from .napcat_sender import SendError, send_group_text
from .perfect_detail import account, fetch_recent_matches
from .provider import fetch_detail, normalize_match_id
from .qq_check import credentials
from .report import IncompleteMatch


def _napcat_settings() -> tuple[str, int]:
    path = Path(__file__).resolve().parent.parent / ".env"
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"\'')
    token = os.environ.get("NAPCAT_ACCESS_TOKEN", values.get("NAPCAT_ACCESS_TOKEN", ""))
    port = int(os.environ.get("NAPCAT_HTTP_PORT", values.get("NAPCAT_HTTP_PORT", "3000")))
    if not token or not 1 <= port <= 65535:
        raise ValueError("请配置本机 NapCat 访问令牌和 HTTP 端口")
    return token, port


class ReportMonitor:
    def __init__(self, store: BindingStore):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS report_routes (
                app TEXT NOT NULL, group_id TEXT NOT NULL, qq_group_id TEXT NOT NULL,
                PRIMARY KEY(app,group_id), UNIQUE(qq_group_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS report_watchers (
                app TEXT NOT NULL, group_id TEXT NOT NULL, steam_id TEXT NOT NULL,
                PRIMARY KEY(app,group_id,steam_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS report_observations (
                app TEXT NOT NULL, group_id TEXT NOT NULL, steam_id TEXT NOT NULL,
                match_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('seen','pending')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(app,group_id,steam_id,match_id))""")

    def set_route(self, app: str, group: str, qq_group: str) -> None:
        if not app or not group or not re.fullmatch(r"[1-9][0-9]{4,11}", qq_group):
            raise ValueError("群标识格式无效")
        with self.store.transaction() as db:
            db.execute("""INSERT INTO report_routes(app,group_id,qq_group_id) VALUES(?,?,?)
                ON CONFLICT(app,group_id) DO UPDATE SET qq_group_id=excluded.qq_group_id""",
                (app, group, qq_group))

    def routes(self) -> list[tuple[str, str, str]]:
        with self.store.transaction() as db:
            return [tuple(row) for row in db.execute(
                "SELECT app,group_id,qq_group_id FROM report_routes ORDER BY app,group_id")]

    def _observe(self, app: str, group: str, steam: str, rows: list[dict]) -> None:
        match_ids = []
        for row in rows:
            try:
                match_id = normalize_match_id(str(row.get("matchId", "")))
                ended = datetime.strptime(row.get("endTime", ""), "%Y-%m-%d %H:%M:%S")
                if datetime.now() - timedelta(hours=24) <= ended <= datetime.now() + timedelta(minutes=5):
                    match_ids.append(match_id)
            except (ValueError, TypeError):
                continue
        with self.store.transaction() as db:
            initialized = db.execute("""INSERT OR IGNORE INTO report_watchers(app,group_id,steam_id)
                VALUES(?,?,?)""", (app, group, steam)).rowcount
            for match_id in set(match_ids):
                db.execute("""INSERT OR IGNORE INTO report_observations
                    (app,group_id,steam_id,match_id,status) VALUES(?,?,?,?,?)""",
                    (app, group, steam, match_id, "seen" if initialized else "pending"))

    def _pending(self, app: str, group: str) -> list[str]:
        with self.store.transaction() as db:
            return [row[0] for row in db.execute("""SELECT DISTINCT match_id FROM report_observations
                WHERE app=? AND group_id=? AND status='pending'
                  AND created_at >= datetime('now','-24 hours') ORDER BY created_at""", (app, group))]

    def _mark_seen(self, app: str, group: str, match_id: str) -> None:
        with self.store.transaction() as db:
            db.execute("""UPDATE report_observations SET status='seen'
                WHERE app=? AND group_id=? AND match_id=?""", (app, group, match_id))

    def _prune_inactive(self, app: str, group: str, active: set[str]) -> None:
        with self.store.transaction() as db:
            old = [row[0] for row in db.execute(
                "SELECT steam_id FROM report_watchers WHERE app=? AND group_id=?", (app, group))]
            for steam in set(old) - active:
                db.execute("DELETE FROM report_watchers WHERE app=? AND group_id=? AND steam_id=?",
                           (app, group, steam))
                db.execute("DELETE FROM report_observations WHERE app=? AND group_id=? AND steam_id=?",
                           (app, group, steam))
            db.execute("DELETE FROM report_observations WHERE created_at < datetime('now','-30 days')")

    def _claim(self, app: str, group: str, match_id: str) -> bool:
        with self.store.transaction() as db:
            return bool(db.execute("""UPDATE report_deliveries SET status='sending',updated_at=CURRENT_TIMESTAMP
                WHERE app=? AND group_id=? AND match_id=? AND report_type='team' AND status='ready'
                  AND EXISTS (SELECT 1 FROM bindings b
                    JOIN member_settings m ON m.app=b.app AND m.group_id=b.group_id AND m.member=b.member
                    JOIN group_settings g ON g.app=b.app AND g.group_id=b.group_id
                    WHERE b.app=report_deliveries.app AND b.group_id=report_deliveries.group_id
                      AND b.steam_id=report_deliveries.target_steam_id AND b.status='verified'
                      AND m.report_opt_in=1 AND g.report_enabled=1)""",
                (app, group, match_id)).rowcount)

    def _finish(self, app: str, group: str, match_id: str, message_id: str | None) -> None:
        with self.store.transaction() as db:
            db.execute("""UPDATE report_deliveries SET status=?,qq_message_id=?,updated_at=CURRENT_TIMESTAMP
                WHERE app=? AND group_id=? AND match_id=? AND report_type='team' AND status='sending'""",
                ("sent" if message_id else "unknown", message_id, app, group, match_id))

    def poll_once(self, napcat_token: str, http_port: int = 3000,
                  *, recent=fetch_recent_matches, detail=fetch_detail, sender=send_group_text) -> int:
        sent = 0
        detail_cache = {}
        recent_cache = {}
        for app, group, qq_group in self.routes():
            members = self.store.eligible_members(app, group)
            active = {member["steam_id"] for member in members}
            self._prune_inactive(app, group, active)
            for steam in active:
                if steam not in recent_cache:
                    try:
                        recent_cache[steam] = recent(steam, limit=10)
                    except (OSError, ValueError):
                        recent_cache[steam] = None
                if recent_cache[steam] is not None:
                    self._observe(app, group, steam, recent_cache[steam])
            for match_id in self._pending(app, group):
                if match_id not in detail_cache:
                    try:
                        detail_cache[match_id] = detail(match_id)
                    except (OSError, ValueError):
                        detail_cache[match_id] = None
                response = detail_cache[match_id]
                if response is None:
                    continue
                try:
                    prepared = prepare_team_report(self.store, app, group, response)
                except IncompleteMatch:
                    continue
                if prepared is None:
                    continue
                # The provider must return the same match we discovered.
                if prepared.match_id != match_id:
                    continue
                if self._claim(app, group, match_id):
                    try:
                        message_id = sender(qq_group, prepared.text,
                                            access_token=napcat_token, port=http_port)
                    except SendError:
                        self._finish(app, group, match_id, None)
                    else:
                        self._finish(app, group, match_id, message_id)
                        sent += 1
                self._mark_seen(app, group, match_id)
        return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="已绑定玩家完美比赛自动战报")
    parser.add_argument("--poll-seconds", type=int, default=90)
    parser.add_argument("--route-group-openid", help="本机配置的官方机器人群 OpenID")
    parser.add_argument("--route-qq-group", help="播报账号所在的 QQ 群号")
    args = parser.parse_args()
    if not 60 <= args.poll_seconds <= 3600:
        parser.error("轮询间隔须为 60～3600 秒")
    monitor = ReportMonitor(BindingStore())
    if args.route_group_openid or args.route_qq_group:
        if not args.route_group_openid or not args.route_qq_group:
            parser.error("配置路由时必须同时填写两个群标识")
        app, _ = credentials()
        monitor.set_route(app, args.route_group_openid, args.route_qq_group)
        print("群播报路由已保存。")
        return
    if account() is None:
        parser.error("请先配置可用的完美平台登录令牌")
    token, port = _napcat_settings()
    print("完美比赛自动监控已启动。", flush=True)
    while True:
        try:
            count = monitor.poll_once(token, port)
            if count:
                print(f"已确认发送 {count} 份完美比赛战报。", flush=True)
        except (OSError, sqlite3.Error) as error:
            print(f"本轮监控失败：{type(error).__name__}；稍后重试。", flush=True)
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
