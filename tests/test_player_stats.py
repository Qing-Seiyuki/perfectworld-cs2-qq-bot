import unittest
from decimal import Decimal

from qq_cs2_bot.player_stats import (PlayerStats, SeasonStats, anomaly_reasons,
                                     recent_average, render_player_stats)


def sample(recent="1.35", season="1.35"):
    return PlayerStats("玩家", SeasonStats("S18", "A", Decimal("1.10")),
                       SeasonStats("S19", "B", Decimal(season)),
                       (Decimal(recent),) * 5)


class PlayerStatsTests(unittest.TestCase):
    def test_strict_thresholds(self):
        self.assertEqual(anomaly_reasons(sample()), ())
        self.assertEqual(anomaly_reasons(sample("1.36", "1.35")),
                         ("最近五场平均 Rating 高于 1.35",))
        self.assertEqual(anomaly_reasons(sample("1.31", "1.00")),
                         ("最近五场平均 Rating 高于本赛季平均 0.30",))
        self.assertEqual(anomaly_reasons(sample("1.00", "1.36")),
                         ("本赛季 Rating 高于 1.35",))
        self.assertEqual(anomaly_reasons(sample("1.30", "1.00")), ())

    def test_partial_history_never_claims_five_match_average(self):
        stats = PlayerStats("玩家", None, SeasonStats("S19", "B", Decimal("1.00")),
                            (Decimal("2.00"),) * 4)
        self.assertIsNone(recent_average(stats))
        self.assertEqual(anomaly_reasons(stats), ())
        self.assertIn("数据不足", render_player_stats(stats))

    def test_current_high_rating_still_alerts_without_recent_matches(self):
        stats = PlayerStats("玩家", None, SeasonStats("S19", "B", Decimal("1.36")), ())
        self.assertEqual(anomaly_reasons(stats), ("本赛季 Rating 高于 1.35",))

    def test_display_separates_best_season_from_current(self):
        text = render_player_stats(sample())
        self.assertIn("历史最高段位：S18｜A｜赛季 Rating 1.10", text)
        self.assertIn("当前段位：S19｜B｜赛季 Rating 1.35", text)
        self.assertIn("最近五场平均完美 Rating：1.35", text)


if __name__ == "__main__":
    unittest.main()
