"""Bounded, read-only player nickname search; does not supply match history."""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import json
import re
from urllib.request import Request, urlopen


SEARCH_URL = "https://appengine.wmpvp.com/steamcn/app/search/user"


@dataclass(frozen=True)
class PlayerCandidate:
    nickname: str
    steam_id: str
    user_id: str
    pvp_score: int | None
    stars: int | None = None


def _parse_candidates(rows: object, query: str) -> list[PlayerCandidate]:
    if not isinstance(rows, list):
        raise ValueError("玩家搜索响应格式异常")
    result = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("pvpNickName")
        if not isinstance(raw_name, str):
            continue
        name = unescape(raw_name)
        steam_id = str(item.get("steamId", ""))
        if name != query and steam_id != query:
            continue
        if not re.fullmatch(r"[0-9]{17}", steam_id) or steam_id in seen:
            continue
        seen.add(steam_id)
        score = item.get("pvpScore")
        score = score if type(score) is int and score >= 0 else None
        stars = item.get("stars")
        stars = stars if type(stars) is int and stars >= 0 else None
        result.append(PlayerCandidate(name, steam_id, str(item.get("userId", "")), score, stars))
    return result


def search_players(query: str) -> list[PlayerCandidate]:
    """Search an exact nickname or SteamID; caller handles ambiguous names."""
    if not isinstance(query, str) or not query.strip() or len(query) > 60:
        raise ValueError("请输入不超过 60 字的完美昵称或 SteamID")
    query = query.strip()
    result = []
    seen = set()
    # Bounded pagination: a full page might hide more exact-name users.
    for page in range(1, 4):
        body = json.dumps({"keyword": query, "page": page}).encode("utf-8")
        request = Request(SEARCH_URL, data=body,
                          headers={"Content-Type": "application/json;charset=UTF-8"}, method="POST")
        with urlopen(request, timeout=12) as response:
            raw = response.read(500_001)
        if len(raw) > 500_000:
            raise ValueError("玩家搜索响应过大")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("code") != 1:
            raise ValueError("玩家搜索暂不可用")
        rows = payload.get("result")
        for candidate in _parse_candidates(rows, query):
            if candidate.steam_id not in seen:
                seen.add(candidate.steam_id)
                result.append(candidate)
        if len(rows) < 10:
            break
    return result
