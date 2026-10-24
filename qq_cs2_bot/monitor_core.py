"""Prepare one team report per group and match from an already-obtained detail.

No polling or QQ sending is performed here. The source adapter and sender are
separate so this can be verified before a compliant recent-match source exists.
"""
from __future__ import annotations

from dataclasses import dataclass

from .bindings import BindingStore
from .report import IncompleteMatch, render_report


@dataclass(frozen=True)
class PreparedReport:
    match_id: str
    target_steam_id: str
    text: str
    newly_queued: bool


def prepare_team_report(store: BindingStore, app: str, group: str, response: dict) -> PreparedReport | None:
    eligible = store.eligible_members(app, group)
    if not eligible:
        return None
    data = response.get("data") if isinstance(response, dict) else None
    base = data.get("base") if isinstance(data, dict) else None
    players = data.get("players") if isinstance(data, dict) else None
    if not isinstance(base, dict) or not isinstance(players, list):
        raise IncompleteMatch("比赛详情未就绪")
    match_id = base.get("matchId")
    if not isinstance(match_id, str) or not match_id:
        raise IncompleteMatch("比赛 ID 缺失")
    teams = {p.get("playerId"): p.get("team") for p in players if isinstance(p, dict)}
    participating = [member for member in eligible if member["steam_id"] in teams]
    if not participating:
        return None
    sides = [teams[member["steam_id"]] for member in participating]
    if any(type(side) is not int or side not in (1, 2) for side in sides) or len(set(sides)) != 1:
        raise IncompleteMatch("群内已订阅成员分属不同队伍，无法确定唯一我方战报")
    # Selection doesn't change the report: any participating subscriber on the
    # same team yields the same five players. One row is keyed by group+match.
    chosen = min(participating, key=lambda member: member["steam_id"])
    text = render_report(response, chosen["steam_id"], qq_labels=store.labels(app, group))
    with store.transaction() as db:
        # A toggle may have changed while the detail was being parsed.
        active = db.execute("""SELECT 1 FROM bindings b
            JOIN member_settings m ON m.app=b.app AND m.group_id=b.group_id AND m.member=b.member
            JOIN group_settings g ON g.app=b.app AND g.group_id=b.group_id
            WHERE b.app=? AND b.group_id=? AND b.steam_id=? AND b.status='verified'
              AND m.report_opt_in=1 AND g.report_enabled=1""",
            (app, group, chosen["steam_id"])).fetchone()
        if not active:
            return None
        inserted = db.execute("""INSERT OR IGNORE INTO report_deliveries
            (app,group_id,match_id,report_type,target_steam_id,status)
            VALUES(?,?,?,'team',?,'ready')""", (app, group, match_id, chosen["steam_id"]))
    return PreparedReport(match_id, chosen["steam_id"], text, bool(inserted.rowcount))


def can_deliver(store: BindingStore, app: str, group: str, match_id: str) -> bool:
    """Recheck switches before any future QQ send; no network calls here."""
    with store.transaction() as db:
        row = db.execute("""SELECT target_steam_id FROM report_deliveries
            WHERE app=? AND group_id=? AND match_id=? AND report_type='team' AND status='ready'""",
            (app, group, match_id)).fetchone()
        if not row:
            return False
        return bool(db.execute("""SELECT 1 FROM bindings b
            JOIN member_settings m ON m.app=b.app AND m.group_id=b.group_id AND m.member=b.member
            JOIN group_settings g ON g.app=b.app AND g.group_id=b.group_id
            WHERE b.app=? AND b.group_id=? AND b.steam_id=? AND b.status='verified'
              AND m.report_opt_in=1 AND g.report_enabled=1""",
            (app, group, row["target_steam_id"])).fetchone())
