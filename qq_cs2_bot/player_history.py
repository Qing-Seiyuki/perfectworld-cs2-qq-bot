"""Find the highest rank visible in season summaries and match-score histories."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import time

from .perfect_detail import fetch_season
from .player_query import _rank
from .player_stats import rating_number


CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "player_seasons.sqlite3"
SEASON_ID = re.compile(r"S([1-9][0-9]?)\Z")


@dataclass(frozen=True)
class Peak:
    season: str
    rank: str
    pw_rating: object
    key: tuple[int, int, int]


def _nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def season_peak(data: dict) -> Peak | None:
    season = data.get("seasonId")
    if not isinstance(season, str) or not SEASON_ID.fullmatch(season):
        return None
    cnt = _nonnegative_int(data.get("cnt"))
    if not cnt:
        return None
    scores = [x for x in (data.get("historyScores") or []) if _nonnegative_int(x) is not None]
    current_score = _nonnegative_int(data.get("pvpScore"))
    if current_score is not None:
        scores.append(current_score)
    score_list = data.get("scoreList") or []
    if isinstance(score_list, list):
        scores.extend(x["score"] for x in score_list if isinstance(x, dict)
                      and _nonnegative_int(x.get("score")) is not None)
    score = max(scores, default=0)
    if score <= 0:
        return None
    rank = _rank(score)
    order = {"D": 1, "C": 2, "C+": 3, "B": 4, "B+": 5, "A": 6, "A+": 7, "S": 8}[rank]
    stars = [_nonnegative_int(data.get("stars"))]
    if isinstance(score_list, list):
        stars.extend(_nonnegative_int(x.get("stars")) for x in score_list if isinstance(x, dict))
    known_stars = [x for x in stars if x is not None]
    star_count = max(known_stars) if known_stars else -1
    display = f"S {star_count}星" if rank == "S" and star_count >= 0 else (
        "S（星数暂无）" if rank == "S" else f"{score}（{rank}）")
    return Peak(season, display, rating_number(data.get("pwRating")),
                (order, star_count if rank == "S" else 0, score))


def historical_best(steam_id: str, current: dict, *, cache_path: Path = CACHE_PATH) -> tuple[Peak | None, bool]:
    """Complete=False means some seasons could not be checked; do not claim a lifetime best."""
    match = SEASON_ID.fullmatch(str(current.get("seasonId", "")))
    if not match:
        return season_peak(current), False
    current_number = int(match.group(1))
    if current_number > 40:
        return season_peak(current), False
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(cache_path, timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS seasons(steam_id TEXT NOT NULL, season TEXT NOT NULL, "
                   "data TEXT NOT NULL, fetched_at INTEGER NOT NULL, PRIMARY KEY(steam_id, season))")
        rows = db.execute("SELECT season, data, fetched_at FROM seasons WHERE steam_id=?", (steam_id,)).fetchall()
        cached = {}
        now = int(time.time())
        for season, raw, fetched_at in rows:
            if now - fetched_at < 7 * 86400:
                try:
                    cached[season] = json.loads(raw)
                except ValueError:
                    pass
        seasons = [f"S{number}" for number in range(1, current_number)]
        missing = [season for season in seasons if season not in cached]
        if missing:
            with ThreadPoolExecutor(max_workers=4) as pool:
                tasks = {pool.submit(fetch_season, steam_id, season): season for season in missing}
                for future in as_completed(tasks):
                    season = tasks[future]
                    try:
                        data = future.result()
                    except Exception:
                        data = None
                    if data is None:
                        continue
                    # Only store the fields needed for historical rank and rating.
                    small = {key: data.get(key) for key in
                             ("seasonId", "cnt", "pvpScore", "stars", "pwRating", "historyScores", "scoreList")}
                    cached[season] = small
                    db.execute("INSERT OR REPLACE INTO seasons VALUES(?,?,?,?)",
                               (steam_id, season, json.dumps(small), now))
        peaks = [peak for data in [current, *(cached[s] for s in seasons if s in cached)]
                 if (peak := season_peak(data)) is not None]
        return max(peaks, key=lambda peak: peak.key, default=None), all(season in cached for season in seasons)
