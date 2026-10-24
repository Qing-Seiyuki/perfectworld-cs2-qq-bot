import unittest

from qq_cs2_bot.provider import normalize_match_id
from qq_cs2_bot.report import IncompleteMatch, render_report


def fixture():
    # Synthetic data only: no real user's identity or match history in tests.
    return {"statusCode": 0, "data": {
        "base": {"matchId": "PVP@1234567890123456789", "map": "测试地图",
                 "endTime": "2026-10-21 01:06:12", "score1": 10, "score2": 13, "winTeam": 2},
        "players": [{"playerId": f"test-{i}", "nickName": "同名玩家", "team": 1 if i < 5 else 2,
                     "kill": 0, "death": 16, "assist": 9, "rating": 0.88, "pwRating": 1.04,
                     "adpr": 70} for i in range(10)]}}


class ReportTests(unittest.TestCase):
    def test_team_two_score_and_identity(self):
        text = render_report(fixture(), "test-8", qq_labels={"test-8": "测试群友"})
        self.assertIn("我方 13∶10", text)
        self.assertIn("胜利", text)
        self.assertEqual(text.count("QQ："), 5)
        self.assertEqual(text.count("测试群友"), 1)
        self.assertEqual(text.count("未绑定"), 4)

    def test_loss(self):
        self.assertIn("失利", render_report(fixture(), "test-0"))

    def test_zero_and_missing_are_distinct(self):
        data = fixture()
        data["data"]["players"][0]["rating"] = None
        text = render_report(data, "test-0", rating_field="rating")
        self.assertIn("0/16/9", text)
        self.assertIn("Rating 暂无", text)

    def test_rating_types(self):
        self.assertIn("完美 Rating 1.04", render_report(fixture(), "test-0", rating_field="pwRating"))

    def test_missing_target(self):
        with self.assertRaises(IncompleteMatch):
            render_report(fixture(), "unknown")

    def test_incomplete_team(self):
        data = fixture()
        data["data"]["players"].pop()
        with self.assertRaises(IncompleteMatch):
            render_report(data, "test-8")

    def test_duplicate_player(self):
        data = fixture()
        data["data"]["players"][1]["playerId"] = "test-0"
        with self.assertRaises(IncompleteMatch):
            render_report(data, "test-0")

    def test_not_ended(self):
        data = fixture()
        data["data"]["base"]["endTime"] = None
        with self.assertRaises(IncompleteMatch):
            render_report(data, "test-0")

    def test_inconsistent_winner(self):
        data = fixture()
        data["data"]["base"]["winTeam"] = 1
        with self.assertRaises(IncompleteMatch):
            render_report(data, "test-0")

    def test_invalid_metrics(self):
        data = fixture()
        data["data"]["players"][0].update(kill=-1, rating=float("nan"), adpr=True)
        self.assertIn("暂无/16/9｜Rating 暂无｜ADR 暂无", render_report(data, "test-0", rating_field="rating"))

    def test_untrusted_name(self):
        data = fixture()
        data["data"]["players"][0]["nickName"] = "a\n[CQ:at,qq=all]"
        self.assertNotIn("[CQ:", render_report(data, "test-0"))

    def test_match_id_precision(self):
        self.assertEqual(normalize_match_id("9219329326884564108"), "PVP@9219329326884564108")
        with self.assertRaises(ValueError):
            normalize_match_id("9.219329326884564e18")


if __name__ == "__main__":
    unittest.main()
