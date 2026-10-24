"""Evaluate a player's Perfect World statistics once a trusted source supplies them.

This module deliberately does not fetch data. In particular, one season's rank or
one match's Rating cannot stand in for a historical peak or a five-match average.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


@dataclass(frozen=True)
class SeasonStats:
    season: str
    rank: str | None
    pw_rating: Decimal | None


@dataclass(frozen=True)
class PlayerStats:
    nickname: str
    historical_best: SeasonStats | None
    current: SeasonStats | None
    recent_pw_ratings: tuple[Decimal, ...]


def rating_number(value: object) -> Decimal | None:
    """Accept only finite, nonnegative source numbers; missing values stay missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def recent_average(stats: PlayerStats) -> Decimal | None:
    # A sample of fewer than five matches is not labelled a five-match average.
    if len(stats.recent_pw_ratings) != 5 or any(rating_number(x) is None for x in stats.recent_pw_ratings):
        return None
    return sum(stats.recent_pw_ratings) / Decimal(5)


def anomaly_reasons(stats: PlayerStats) -> tuple[str, ...]:
    recent = recent_average(stats)
    season = rating_number(stats.current.pw_rating) if stats.current else None
    reasons = []
    if recent is not None and recent > Decimal("1.35"):
        reasons.append("最近五场平均 Rating 高于 1.35")
    if recent is not None and season is not None and recent - season > Decimal("0.30"):
        reasons.append("最近五场平均 Rating 高于本赛季平均 0.30")
    if season is not None and season > Decimal("1.35"):
        reasons.append("本赛季 Rating 高于 1.35")
    return tuple(reasons)


def _one_line(value: str, limit: int = 60) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:limit]


def _rating(value: Decimal | None) -> str:
    valid = rating_number(value)
    return str(valid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if valid is not None else "暂无"


def render_player_stats(stats: PlayerStats) -> str:
    best, current = stats.historical_best, stats.current
    recent = recent_average(stats)
    best_text = (f"{_one_line(best.season)}｜{_one_line(best.rank or '暂无')}｜赛季 Rating {_rating(best.pw_rating)}"
                 if best else "暂无")
    current_text = (f"{_one_line(current.season)}｜{_one_line(current.rank or '暂无')}｜赛季 Rating {_rating(current.pw_rating)}"
                    if current else "暂无")
    lines = [f"【完美 CS2 玩家战绩】{_one_line(stats.nickname)}",
             f"历史最高段位：{best_text}",
             f"当前段位：{current_text}",
             f"最近五场平均完美 Rating：{_rating(recent)}"]
    reasons = anomaly_reasons(stats)
    if reasons:
        lines.append("⚠ 数据异常提醒：" + "；".join(reasons))
        lines.append("仅按设定阈值提示，不代表违规或作弊。")
    elif recent is None or current is None or current.pw_rating is None:
        lines.append("数据不足，无法完整判断异常规则。")
    else:
        lines.append("未触发设定的异常提醒阈值。")
    return "\n".join(lines)
