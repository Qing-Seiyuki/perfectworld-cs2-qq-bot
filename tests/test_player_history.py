import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qq_cs2_bot.player_history import historical_best, season_peak


STEAM = "76561199117265694"


class PlayerHistoryTests(unittest.TestCase):
    def test_season_peak_uses_history_score_and_explicit_stars(self):
        a = season_peak({"seasonId": "S1", "cnt": 3, "pvpScore": 1901,
                         "historyScores": [1901, 2051, 2000], "pwRating": 1.23})
        self.assertEqual(a.rank, "2051（A+）")
        s = season_peak({"seasonId": "S2", "cnt": 3, "pvpScore": 2401,
                         "historyScores": [2600], "stars": 5,
                         "scoreList": [{"score": 2600, "stars": 7}], "pwRating": 1.11})
        self.assertEqual(s.rank, "S 7星")
        self.assertGreater(s.key, a.key)
        self.assertIsNone(season_peak({"seasonId": "S3", "cnt": 0, "pvpScore": 0}))

    @patch("qq_cs2_bot.player_history.fetch_season")
    def test_historical_scan_and_cache(self, fetch):
        fetch.side_effect = lambda steam, season: {
            "S1": {"seasonId": "S1", "cnt": 2, "pvpScore": 1500, "stars": 0, "pwRating": 1.01},
            "S2": {"seasonId": "S2", "cnt": 2, "pvpScore": 2401, "stars": 8, "pwRating": 1.30},
        }[season]
        current = {"seasonId": "S3", "cnt": 2, "pvpScore": 2000,
                   "stars": 0, "pwRating": 1.20}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.sqlite3"
            best, complete = historical_best(STEAM, current, cache_path=path)
            self.assertTrue(complete)
            self.assertEqual((best.season, best.rank), ("S2", "S 8星"))
            best, complete = historical_best(STEAM, current, cache_path=path)
            self.assertTrue(complete)
            self.assertEqual(fetch.call_count, 2)

    @patch("qq_cs2_bot.player_history.fetch_season", return_value=None)
    def test_incomplete_scan_cannot_claim_lifetime_best(self, fetch):
        current = {"seasonId": "S2", "cnt": 2, "pvpScore": 1800,
                   "stars": 0, "pwRating": 1.10}
        with tempfile.TemporaryDirectory() as folder:
            best, complete = historical_best(STEAM, current,
                                             cache_path=Path(folder) / "cache.sqlite3")
        self.assertFalse(complete)
        self.assertEqual(best.rank, "1800（B+）")


if __name__ == "__main__":
    unittest.main()
