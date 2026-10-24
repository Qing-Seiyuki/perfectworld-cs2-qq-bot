import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qq_cs2_bot.perfect_detail import account, fetch_stars, fetch_recent_matches, fetch_match_page
from qq_cs2_bot.perfect_login import login, save_account


OWN = "76561199117265694"
TARGET = "76561199690813601"


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return self.payload[:limit]


class Opener:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def open(self, request, timeout):
        self.request = request
        return Response(self.payload)


class PerfectDetailTests(unittest.TestCase):
    @patch("qq_cs2_bot.perfect_detail.build_opener")
    def test_recent_matches_filters_wrong_player(self, build):
        opener = Opener({"statusCode": 0, "data": {"dataPublic": True, "matchList": [
            {"playerId": TARGET, "matchId": "PVP@one"},
            {"playerId": OWN, "matchId": "PVP@two"}]}})
        build.return_value = opener
        result = fetch_recent_matches(TARGET, credentials=("secret", OWN))
        self.assertEqual([row["matchId"] for row in result], ["PVP@one"])
        request = json.loads(opener.request.data)
        self.assertEqual((request["mySteamId"], request["toSteamId"], request["pageSize"]),
                         (int(OWN), int(TARGET), 5))

    @patch("qq_cs2_bot.perfect_detail.build_opener")
    def test_paginated_match_page_keeps_number_positions(self, build):
        opener = Opener({"statusCode": 0, "data": {"dataPublic": True, "matchList": [
            {"playerId": TARGET, "matchId": "PVP@9219329326884564108"}]}})
        build.return_value = opener
        rows = fetch_match_page(TARGET, 2, credentials=("secret", OWN))
        self.assertEqual(len(rows), 1)
        payload = json.loads(opener.request.data)
        self.assertEqual((payload["page"], payload["pageSize"]), (2, 8))
        opener.payload["data"]["matchList"].insert(0, {"playerId": OWN})
        self.assertIsNone(fetch_match_page(TARGET, 2, credentials=("secret", OWN)))

    @patch("qq_cs2_bot.perfect_detail.build_opener")
    def test_explicit_stars_and_matching_identity_required(self, build):
        opener = Opener({"statusCode": 0, "data": {"steamId": TARGET, "stars": 170}})
        build.return_value = opener
        self.assertEqual(fetch_stars(TARGET, credentials=("secret", OWN)), 170)
        self.assertEqual(opener.request.get_header("Token"), "secret")
        self.assertIn(OWN, opener.request.data.decode())
        opener.payload["data"]["steamId"] = OWN
        self.assertIsNone(fetch_stars(TARGET, credentials=("secret", OWN)))
        opener.payload["data"]["steamId"] = TARGET
        opener.payload["data"].pop("stars")
        self.assertIsNone(fetch_stars(TARGET, credentials=("secret", OWN)))

    @patch("qq_cs2_bot.perfect_login.build_opener")
    def test_login_keeps_token_local_and_stores_without_replacing_other_secrets(self, build):
        build.return_value = Opener({"code": 0, "result": {"loginResult": {
            "accountInfo": {"token": "test-token", "steamId": int(OWN)}}}})
        token, steam_id = login("13800138000", "123456")
        self.assertEqual((token, steam_id), ("test-token", OWN))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("QQ_APP_SECRET=qq-secret\n", encoding="utf-8")
            save_account(token, steam_id, path)
            self.assertIn("QQ_APP_SECRET=qq-secret", path.read_text(encoding="utf-8"))
            self.assertEqual(account(path), (token, steam_id))
            save_account("new-token", steam_id, path)
            self.assertEqual(path.read_text(encoding="utf-8").count("PERFECT_TOKEN="), 1)


if __name__ == "__main__":
    unittest.main()
