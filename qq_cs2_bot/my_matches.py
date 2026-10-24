"""Compact, group-safe views of a verified member's own Perfect matches."""
from __future__ import annotations

from .provider import normalize_match_id
from .report import clean

PAGE_SIZE = 8
MAX_PAGE = 100


def page_for_number(number: int) -> tuple[int, int]:
    if type(number) is not int or not 1 <= number <= PAGE_SIZE * MAX_PAGE:
        raise ValueError("比赛序号须在 1～800 之间")
    return (number - 1) // PAGE_SIZE + 1, (number - 1) % PAGE_SIZE


def select_match_id(rows: list[dict], number: int) -> str | None:
    _, index = page_for_number(number)
    if index >= len(rows):
        return None
    try:
        return normalize_match_id(str(rows[index].get("matchId", "")))
    except ValueError:
        return None


def render_match_list(rows: list[dict], page: int) -> str:
    if not rows:
        return "没有更多比赛记录。" if page > 1 else "绑定账号暂无近期比赛记录。"
    lines = [f"【我的比赛列表】第 {page} 页（每页 8 场）"]
    for index, row in enumerate(rows, (page - 1) * PAGE_SIZE + 1):
        team = row.get("team")
        own = row.get(f"score{team}") if type(team) is int and team in (1, 2) else None
        enemy = row.get(f"score{3-team}") if type(team) is int and team in (1, 2) else None
        result = ("胜" if own > enemy else "负" if own < enemy else "平") if (
            type(own) is int and type(enemy) is int) else "结果暂无"
        score = f"{own}∶{enemy}" if type(own) is int and type(enemy) is int else "比分暂无"
        ended = clean(row.get("endTime") or "时间暂无")[:16]
        map_name = clean(row.get("mapName") or "地图暂无")[:20]
        lines.append(f"{index}. {ended}｜{map_name}｜{result} {score}")
    lines.append("发送 @donk666 /数字 查看该场完整战报；也可发送 /我的比赛 数字。")
    if len(rows) == PAGE_SIZE and page < MAX_PAGE:
        lines.append(f"下一页：@donk666 /我的比赛列表 {page + 1}")
    return "\n".join(lines)
