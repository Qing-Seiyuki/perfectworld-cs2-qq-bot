"""Read-only experimental adapter. No bundled credentials or background polling."""
from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

DETAIL_URL = "https://api.wmpvp.com/api/v1/csgo/match"


def normalize_match_id(value: str) -> str:
    if not re.fullmatch(r"(?:PVP@)?[0-9]{19}", value):
        raise ValueError("请输入 19 位完美比赛 ID，可带 PVP@ 前缀")
    return value if value.startswith("PVP@") else "PVP@" + value


def fetch_detail(match_id: str) -> dict:
    match_id = normalize_match_id(match_id)
    body = json.dumps({"matchId": match_id, "platform": "admin", "dataSource": "3"}).encode()
    request = Request(DETAIL_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    # Standard TLS verification, finite timeout and bounded response; no automatic retries.
    with urlopen(request, timeout=15) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("响应超出大小限制")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("statusCode") != 0:
        raise ValueError("数据源拒绝查询或暂不可用")
    if not isinstance(result.get("data"), dict) or result["data"].get("base", {}).get("matchId") != match_id:
        raise ValueError("响应比赛 ID 与请求不一致")
    return result
