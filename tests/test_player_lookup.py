import json
import unittest
from unittest.mock import patch

from qq_cs2_bot.player_lookup import _parse_candidates, search_players


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return self.payload[:limit]


class PlayerLookupTests(unittest.TestCase):
    def test_decodes_entities_and_rejects_fuzzy_matches(self):
        rows = [{"pvpNickName": "❀L&egrave;a!!!❀", "steamId": "76561199117265694",
                 "userId": 123, "pvpScore": 1947},
                {"pvpNickName": "Lèa", "steamId": "76561199117265695"}]
        result = _parse_candidates(rows, "❀Lèa!!!❀")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pvp_score, 1947)

    def test_keeps_star_count_only_when_explicitly_supplied(self):
        steam_id = "76561199117265694"
        rows = [{"pvpNickName": "高手", "steamId": steam_id,
                 "pvpScore": 2450, "stars": 3}]
        self.assertEqual(_parse_candidates(rows, "高手")[0].stars, 3)
        rows[0].pop("stars")
        self.assertIsNone(_parse_candidates(rows, "高手")[0].stars)

    @patch("qq_cs2_bot.player_lookup.urlopen")
    def test_keeps_ambiguous_exact_names_for_caller_choice(self, open_url):
        open_url.return_value = _Response({"code": 1, "result": [
            {"pvpNickName": "同名", "steamId": "76561199117265694", "userId": 1},
            {"pvpNickName": "同名", "steamId": "76561199117265695", "userId": 2}]})
        result = search_players("同名")
        self.assertEqual([x.steam_id for x in result],
                         ["76561199117265694", "76561199117265695"])
        self.assertEqual(open_url.call_count, 1)

    def test_rejects_invalid_input(self):
        with self.assertRaises(ValueError):
            search_players(" " * 10)

    def test_steam_id_selects_one_candidate(self):
        rows = [{"pvpNickName": "同名", "steamId": "76561199117265694"},
                {"pvpNickName": "同名", "steamId": "76561199117265695"}]
        result = _parse_candidates(rows, "76561199117265695")
        self.assertEqual([x.steam_id for x in result], ["76561199117265695"])


if __name__ == "__main__":
    unittest.main()
