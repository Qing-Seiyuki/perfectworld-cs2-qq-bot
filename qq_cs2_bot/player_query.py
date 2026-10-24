"""QQ text for the presently available player identity lookup."""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

from .player_lookup import PlayerCandidate
from .player_stats import PlayerStats, SeasonStats, anomaly_reasons, rating_number, recent_average


def _rank(score: int | None) -> str:
    if score is None:
        return "暂无"
    if score == 0:
        return "未定级"
    if score > 2400:
        return "S"
    for upper, name in ((1000, "D"), (1150, "C"), (1300, "C+"),
                        (1450, "C+"), (1600, "B"), (1750, "B+"),
                        (1900, "B+"), (2050, "A"), (2200, "A+"),
                        (2400, "A+")):
        if score <= upper:
            return name
    raise AssertionError("unreachable")


def _rank_display(candidate: PlayerCandidate) -> str:
    rank = _rank(candidate.pvp_score)
    if rank == "S":
        return f"当前段位：S {candidate.stars}星" if candidate.stars is not None else "当前段位：S（星数暂无）"
    if candidate.pvp_score is None:
        return "当前天梯分：暂无（段位暂无）"
    if rank == "未定级":
        return "当前段位：未定级"
    return f"当前天梯分：{candidate.pvp_score}（{rank}）"


def render_lookup(candidates: list[PlayerCandidate], *, selection_command: str = "数据") -> str:
    if not candidates:
        return "未找到完全匹配的完美昵称或 SteamID。请核对昵称中的符号、大小写和空格。"
    if len(candidates) > 1:
        lines = ["找到多位同名玩家，请用对应 SteamID 选择："]
        for candidate in candidates:
            lines.append(f"{candidate.steam_id}｜{_rank_display(candidate)}")
        lines.append(f"发送：{selection_command} 选中的SteamID")
        return "\n".join(lines)
    candidate = candidates[0]
    nickname = re.sub(r"[\x00-\x1f\x7f]", " ", candidate.nickname)[:60]
    return (f"【完美玩家查询】{nickname}\n"
            f"SteamID：{candidate.steam_id}\n"
            f"{_rank_display(candidate)}\n"
            "历史最高段位、本赛季 Rating、最近五场平均 Rating：暂不可查。\n"
            "完美详细数据暂不可用，因此暂不作数据异常判断。")


def _decimal(value: object) -> str:
    number = rating_number(value)
    return str(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if number is not None else "暂无"


def _recent_ratings(matches: list[dict] | None) -> tuple[Decimal, ...]:
    if matches is None or len(matches) < 5:
        return ()
    ratings = tuple(rating_number(row.get("pwRating")) for row in matches[:5])
    return ratings if all(value is not None for value in ratings) else ()


def render_player_data(candidate: PlayerCandidate, current: dict,
                       best: object, history_complete: bool,
                       matches: list[dict] | None) -> str:
    from .player_history import Peak

    nickname = re.sub(r"[\x00-\x1f\x7f]", " ", candidate.nickname)[:60]
    season = str(current.get("seasonId") or "本赛季")
    score = current.get("pvpScore")
    score = score if type(score) is int and score >= 0 else candidate.pvp_score
    stars = current.get("stars")
    stars = stars if type(stars) is int and stars >= 0 else candidate.stars
    current_candidate = PlayerCandidate(nickname, candidate.steam_id, candidate.user_id, score, stars)
    rank_text = _rank_display(current_candidate).replace("当前", "", 1)
    current_rating = rating_number(current.get("pwRating")) if current.get("cnt", 0) else None
    ratings = _recent_ratings(matches)
    stats = PlayerStats(nickname, None, SeasonStats(season, None, current_rating), ratings)
    recent = recent_average(stats)
    lines = [f"【完美 CS2 玩家数据】{nickname}", f"SteamID：{candidate.steam_id}",
             f"当前{rank_text}｜{season} 完美 Rating {_decimal(current_rating)}"]
    if isinstance(best, Peak):
        label = "历史最高段位" if history_complete else "已查赛季最高段位"
        lines.append(f"{label}：{best.rank}（{best.season}）｜该赛季完美 Rating {_decimal(best.pw_rating)}")
    else:
        lines.append("历史最高段位：暂无")
    lines.append(f"最近五场平均完美 Rating：{_decimal(recent)}" if recent is not None else
                 "最近五场平均完美 Rating：暂无（不足五场或数据缺失）")
    reasons = anomaly_reasons(stats)
    if reasons:
        lines.append("⚠ 数据异常提醒：" + "；".join(reasons))
        lines.append("仅按设定阈值提示，不代表违规或作弊。")
    elif recent is None or current_rating is None:
        lines.append("数据不足，无法完整判断异常规则。")
    else:
        lines.append("未触发设定的异常提醒阈值。")
    if not history_complete:
        lines.append("部分历史赛季暂未取到，最高段位仅供参考。")
    else:
        lines.append("历史段位依据各赛季可查分数、星数及最近记录；更早的赛季内峰值可能缺失。")
    lines.append("发送“最近比赛 " + candidate.steam_id + "”查看最近五场。")
    return "\n".join(lines)


def render_recent_matches(candidate: PlayerCandidate, matches: list[dict] | None) -> str:
    if matches is None:
        return "最近比赛暂不可查，请稍后重试。"
    if not matches:
        return "暂未查到最近比赛。"
    nickname = re.sub(r"[\x00-\x1f\x7f]", " ", candidate.nickname)[:60]
    lines = [f"【最近比赛】{nickname}｜{candidate.steam_id}"]
    for number, row in enumerate(matches[:5], 1):
        team = row.get("team")
        own = row.get(f"score{team}") if team in (1, 2) else None
        enemy = row.get(f"score{3-team}") if team in (1, 2) else None
        score = f"{own}∶{enemy}" if type(own) is int and type(enemy) is int else "比分暂无"
        outcome = ("胜" if own > enemy else "负" if own < enemy else "平") if type(own) is int and type(enemy) is int else ""
        date = str(row.get("endTime") or "时间暂无")[:16]
        map_name = re.sub(r"[\x00-\x1f\x7f]", " ", str(row.get("mapName") or "地图暂无"))[:20]
        kda = "/".join(str(row[key]) if type(row.get(key)) is int and row[key] >= 0 else "暂无"
                       for key in ("kill", "death", "assist"))
        match_id = str(row.get("matchId") or "暂无")
        lines.append(f"{number}. {date}｜{map_name}｜{outcome}{score}｜{kda}｜完美 Rating {_decimal(row.get('pwRating'))}")
        lines.append(f"   比赛ID：{match_id}")
    return "\n".join(lines)
