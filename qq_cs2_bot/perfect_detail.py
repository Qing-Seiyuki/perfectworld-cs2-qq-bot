"""Read player season summaries and matches with a local Perfect World login."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .bindings import valid_steam_id


DETAIL_URL = "https://api.wmpvp.com/api/csgo/home/pvp/detailStats"
MATCH_LIST_URL = "https://api.wmpvp.com/api/csgo/home/match/list"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def account(path: Path = ENV_PATH) -> tuple[str, str] | None:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"\'')
    token = os.environ.get("PERFECT_TOKEN", values.get("PERFECT_TOKEN", ""))
    steam_id = os.environ.get("PERFECT_STEAM_ID", values.get("PERFECT_STEAM_ID", ""))
    return (token, steam_id) if token and valid_steam_id(steam_id) else None


def _post(url: str, steam_id: str, parameters: dict, credentials: tuple[str, str] | None) -> dict | None:
    if not valid_steam_id(steam_id):
        return None
    credentials = credentials if credentials is not None else account()
    if credentials is None:
        return None
    token, own_steam_id = credentials
    body = json.dumps({"mySteamId": int(own_steam_id), "toSteamId": int(steam_id),
                       **parameters}).encode()
    request = Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "appversion": "4.1.9.229",
        "platform": "android", "token": token,
    })
    try:
        with build_opener(_NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(500_001)
        if len(raw) > 500_000:
            return None
        result = json.loads(raw)
    except (HTTPError, URLError, OSError, ValueError):
        return None
    if not isinstance(result, dict) or result.get("statusCode") != 0:
        return None
    data = result.get("data")
    return data if isinstance(data, dict) else None


def fetch_season(steam_id: str, season_id: str | None = None,
                 *, credentials: tuple[str, str] | None = None) -> dict | None:
    parameters = {"csgoSeasonId": season_id} if season_id else {}
    data = _post(DETAIL_URL, steam_id, parameters, credentials)
    if not isinstance(data, dict) or str(data.get("steamId", "")) != steam_id:
        return None
    if season_id and data.get("seasonId") != season_id:
        return None
    return data


def fetch_stars(steam_id: str, *, credentials: tuple[str, str] | None = None) -> int | None:
    """Return an explicit source star count, or None without guessing from score."""
    data = fetch_season(steam_id, credentials=credentials)
    if data is None:
        return None
    stars = data.get("stars")
    return stars if type(stars) is int and stars >= 0 else None


def fetch_recent_matches(steam_id: str, *, limit: int = 5,
                         credentials: tuple[str, str] | None = None) -> list[dict] | None:
    if not 1 <= limit <= 10:
        raise ValueError("比赛查询数量应在 1 到 10 之间")
    data = _post(MATCH_LIST_URL, steam_id, {
        "csgoSeasonId": "recent", "dataSource": 3, "page": 1,
        "pageSize": limit, "pvpType": -1,
    }, credentials)
    if not isinstance(data, dict) or data.get("dataPublic") is False:
        return None
    rows = data.get("matchList")
    if not isinstance(rows, list):
        return None
    return [row for row in rows if isinstance(row, dict)
            and str(row.get("playerId", "")) == steam_id][:limit]


def fetch_match_page(steam_id: str, page: int, *, page_size: int = 8,
                     credentials: tuple[str, str] | None = None) -> list[dict] | None:
    """Return one page of a player's recent matches; None means source failure."""
    if type(page) is not int or not 1 <= page <= 100 or type(page_size) is not int or not 1 <= page_size <= 10:
        raise ValueError("比赛页码或每页数量无效")
    data = _post(MATCH_LIST_URL, steam_id, {
        "csgoSeasonId": "recent", "dataSource": 3, "page": page,
        "pageSize": page_size, "pvpType": -1,
    }, credentials)
    if not isinstance(data, dict) or data.get("dataPublic") is False:
        return None
    rows = data.get("matchList")
    if not isinstance(rows, list):
        return None
    # Reject a whole page with mismatched player IDs: dropping rows would shift
    # the numbered selection and could show the wrong match.
    if any(not isinstance(row, dict) or str(row.get("playerId", "")) != steam_id for row in rows):
        return None
    return rows[:page_size]
