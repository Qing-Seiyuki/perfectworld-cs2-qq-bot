import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qq_cs2_bot.binding_commands import reply_to_binding
from qq_cs2_bot.bindings import BindingStore
from qq_cs2_bot.player_lookup import PlayerCandidate
from qq_cs2_bot.player_query import _rank, render_lookup, render_player_data
from qq_cs2_bot.player_history import Peak


def event(message, content):
    return {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {
        "id": message, "content": content, "group_openid": "group-a",
        "author": {"member_openid": "member-a"}}}


class PlayerQueryTests(unittest.TestCase):
    def setUp(self):
        self.season = self.enterContext(patch("qq_cs2_bot.binding_commands.fetch_season", return_value=None))
        self.matches = self.enterContext(patch("qq_cs2_bot.binding_commands.fetch_recent_matches", return_value=None))
        self.history = self.enterContext(patch("qq_cs2_bot.binding_commands.historical_best",
                                               return_value=(None, False)))

    def test_rank_boundaries_match_supplied_chart(self):
        cases = ((0, "未定级"), (1000, "D"), (1001, "C"), (1150, "C"),
                 (1151, "C+"), (1300, "C+"), (1301, "C+"),
                 (1450, "C+"), (1451, "B"), (1600, "B"),
                 (1601, "B+"), (1750, "B+"), (1751, "B+"),
                 (1900, "B+"), (1901, "A"), (2050, "A"),
                 (2051, "A+"), (2200, "A+"), (2201, "A+"),
                 (2400, "A+"), (2401, "S"))
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(_rank(score), expected)

    def test_s_rank_hides_score_and_uses_real_stars_only(self):
        candidate = PlayerCandidate("高手", "76561199117265694", "1", 2540, 7)
        result = render_lookup([candidate])
        self.assertIn("当前段位：S 7星", result)
        self.assertNotIn("2540", result)
        unknown = render_lookup([PlayerCandidate("高手", candidate.steam_id, "1", 2540)])
        self.assertIn("当前段位：S（星数暂无）", unknown)
        self.assertNotIn("2540", unknown)

    def test_non_s_score_includes_rank(self):
        result = render_lookup([PlayerCandidate("玩家", "76561199117265694", "1", 1947)])
        self.assertIn("当前天梯分：1947（A）", result)

    def test_full_data_uses_five_match_average_and_anomaly_rules(self):
        candidate = PlayerCandidate("玩家", "76561199117265694", "1", 1947)
        current = {"seasonId": "S25", "pvpScore": 1947, "cnt": 10, "pwRating": 1.00}
        matches = [{"pwRating": 1.40}] * 5
        best = Peak("S24", "2000（A）", 1.10, (6, 0, 2000))
        result = render_player_data(candidate, current, best, True, matches)
        self.assertIn("S25 完美 Rating 1.00", result)
        self.assertIn("该赛季完美 Rating 1.10", result)
        self.assertIn("最近五场平均完美 Rating：1.40", result)
        self.assertIn("最近五场平均 Rating 高于 1.35", result)
        self.assertIn("最近五场平均 Rating 高于本赛季平均 0.30", result)

    @patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"})
    @patch("qq_cs2_bot.binding_commands.search_players")
    def test_s_query_enriches_with_account_star_count(self, search, send):
        steam_id = "76561199690813601"
        search.return_value = [PlayerCandidate("高手", steam_id, "1", 2401)]
        self.season.return_value = {"seasonId": "S25", "steamId": steam_id, "pvpScore": 2401,
                                    "stars": 170, "pwRating": 1.17, "cnt": 10}
        self.history.return_value = (Peak("S25", "S 171星", 1.17, (8, 171, 2401)), True)
        with tempfile.TemporaryDirectory() as folder:
            store = BindingStore(Path(folder) / "db.sqlite3")
            self.assertTrue(reply_to_binding(event("s-rank", f"数据 {steam_id}"), "token", "app-a", store))
        self.season.assert_called_once_with(steam_id)
        response = send.call_args.kwargs["payload"]["content"]
        self.assertIn("S 170星", response)
        self.assertIn("历史最高段位：S 171星", response)
        self.assertNotIn("2401", response)

    @patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"})
    @patch("qq_cs2_bot.binding_commands.search_players")
    def test_recent_matches_command(self, search, send):
        steam_id = "76561199690813601"
        search.return_value = [PlayerCandidate("高手", steam_id, "1", 2401)]
        self.matches.return_value = [{"playerId": steam_id, "matchId": "PVP@123",
                                      "endTime": "2026-10-24 00:11:04", "mapName": "炙热沙城Ⅱ",
                                      "team": 1, "score1": 13, "score2": 5,
                                      "kill": 15, "death": 11, "assist": 7, "pwRating": 1.26}]
        with tempfile.TemporaryDirectory() as folder:
            store = BindingStore(Path(folder) / "db.sqlite3")
            self.assertTrue(reply_to_binding(event("recent", f"最近比赛 {steam_id}"), "token", "app-a", store))
        self.season.assert_not_called()
        self.assertIn("胜13∶5｜15/11/7｜完美 Rating 1.26",
                      send.call_args.kwargs["payload"]["content"])

    def test_ambiguous_names_require_selection(self):
        result = render_lookup([
            PlayerCandidate("同名", "76561199117265694", "1", 1500),
            PlayerCandidate("同名", "76561199117265695", "2", 1800)])
        self.assertIn("数据 选中的SteamID", result)
        self.assertIn("76561199117265694", result)
        self.assertIn("76561199117265695", result)

    @patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"})
    @patch("qq_cs2_bot.binding_commands.search_players")
    def test_nickname_query_replies_without_binding(self, search, send):
        search.return_value = [PlayerCandidate("❀Lèa!!!❀", "76561199117265694", "1", 1947)]
        with tempfile.TemporaryDirectory() as folder:
            store = BindingStore(Path(folder) / "db.sqlite3")
            self.assertTrue(reply_to_binding(event("one", "<@123> /数据 ❀Lèa!!!❀"), "token", "app-a", store))
            self.assertFalse(reply_to_binding(event("one", "<@123> /数据 ❀Lèa!!!❀"), "token", "app-a", store))
        search.assert_called_once_with("❀Lèa!!!❀")
        self.assertIn("暂不作数据异常判断", send.call_args.kwargs["payload"]["content"])
        send.assert_called_once()

    @patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"})
    @patch("qq_cs2_bot.binding_commands.search_players")
    def test_direct_steam_id_query_without_nickname_search(self, search, send):
        search.return_value = [PlayerCandidate("玩家", "76561199117265694", "1", 1947)]
        with tempfile.TemporaryDirectory() as folder:
            store = BindingStore(Path(folder) / "db.sqlite3")
            self.assertTrue(reply_to_binding(event("steam", "<@123> 战绩 76561199117265694"),
                                             "token", "app-a", store))
        search.assert_called_once_with("76561199117265694")
        self.assertIn("SteamID：76561199117265694", send.call_args.kwargs["payload"]["content"])

    @patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"})
    @patch("qq_cs2_bot.binding_commands.search_players")
    def test_bad_steam_id_gives_format_help(self, search, send):
        with tempfile.TemporaryDirectory() as folder:
            store = BindingStore(Path(folder) / "db.sqlite3")
            self.assertTrue(reply_to_binding(event("bad", "战绩 7656119911726569"),
                                             "token", "app-a", store))
        search.assert_not_called()
        self.assertIn("SteamID 格式不正确", send.call_args.kwargs["payload"]["content"])


if __name__ == "__main__":
    unittest.main()
