"""Strict conversion of observed Perfect World responses into plain text."""
from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any


class IncompleteMatch(ValueError):
    """The response cannot yet be used as a final five-player report."""


def clean(value: object) -> str:
    # Keep untrusted player names on a single line; gateways must send plain text.
    return " ".join(str(value).split()).replace("[CQ:", "［CQ:")


def metric(value: Any, decimals: int | None = None) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "暂无"
    if not math.isfinite(value) or value < 0:
        return "暂无"
    if decimals is None:
        return str(value) if int(value) == value else "暂无"
    return f"{value:.{decimals}f}"


def render_report(
    response: Mapping[str, Any],
    steam_id: str,
    *,
    qq_labels: Mapping[str, str] | None = None,
    rating_field: str = "pwRating",
) -> str:
    """QQ labels are supplied by verified, group-scoped bindings, never by PW."""
    if rating_field not in ("rating", "pwRating"):
        raise ValueError("Rating 类型只能是 rating 或 pwRating")
    if response.get("statusCode") != 0:
        raise IncompleteMatch("数据源未返回成功结果")
    data = response.get("data")
    if not isinstance(data, dict):
        raise IncompleteMatch("比赛详情缺失")
    base, players = data.get("base"), data.get("players")
    if not isinstance(base, dict) or not isinstance(players, list):
        raise IncompleteMatch("比赛基础信息或玩家列表缺失")
    if not all(isinstance(p, dict) for p in players):
        raise IncompleteMatch("玩家数据格式异常")
    if not isinstance(base.get("matchId"), str) or not base["matchId"]:
        raise IncompleteMatch("比赛 ID 缺失")
    try:
        datetime.strptime(base.get("endTime", ""), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        raise IncompleteMatch("比赛结束时间缺失或无效，等待数据同步") from None
    ids = [p.get("playerId") for p in players]
    if any(not isinstance(pid, str) or not pid for pid in ids):
        raise IncompleteMatch("玩家标识缺失；不能依赖昵称匹配")
    if len(ids) != len(set(ids)):
        raise IncompleteMatch("玩家数据重复")
    target = next((p for p in players if p["playerId"] == steam_id), None)
    if target is None:
        raise IncompleteMatch("这场比赛未找到指定 SteamID")
    team = target.get("team")
    if type(team) is not int or team not in (1, 2):
        raise IncompleteMatch("无法确认我方队伍")
    teammates = [p for p in players if type(p.get("team")) is int and p["team"] == team]
    if len(teammates) != 5:
        raise IncompleteMatch("我方队伍不足或超过五人，等待完整数据")
    own, enemy = base.get(f"score{team}"), base.get(f"score{3-team}")
    if any(type(s) is not int or s < 0 for s in (own, enemy)):
        raise IncompleteMatch("最终比分缺失或无效")
    winner = base.get("winTeam")
    if own != enemy and (type(winner) is not int or winner != (team if own > enemy else 3-team)):
        raise IncompleteMatch("比分和胜负状态不一致，等待数据同步")
    result = "胜利" if own > enemy else "失利" if own < enemy else "平局"
    label = "Rating" if rating_field == "rating" else "完美 Rating"
    lines = [
        f"【完美 CS2 战报】{result}",
        f"地图：{clean(base.get('map') or '暂无')}｜我方 {own}∶{enemy} 对方",
        f"结束时间：{clean(base['endTime'])}",
        f"比赛：{clean(base['matchId'])}",
        f"我方五人｜击杀/死亡/助攻｜{label}｜ADR",
    ]
    for index, p in enumerate(teammates, 1):
        qq = (qq_labels or {}).get(p["playerId"], "未绑定")
        kda = "/".join(metric(p.get(k)) for k in ("kill", "death", "assist"))
        lines.append(
            f"{index}. QQ：{clean(qq)}｜完美：{clean(p.get('nickName') or '暂无')}\n"
            f"   {kda}｜{label} {metric(p.get(rating_field), 2)}｜ADR {metric(p.get('adpr'), 1)}"
        )
    lines.append("注：QQ 称呼由已验证群友自行设置；暂无表示数据源未提供有效数值。" if qq_labels else
                 "注：QQ 信息来自群内绑定；暂无表示数据源未提供有效数值。")
    return "\n".join(lines)
