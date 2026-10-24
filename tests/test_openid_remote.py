import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener
from unittest.mock import patch

from qq_cs2_bot.bindings import BindingStore
from qq_cs2_bot.openid_remote import checked_public_url, create_server, link_for_request
from qq_cs2_bot.qq_check import NoRedirect

STEAM = "76561199117265694"


class RemoteVerificationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = BindingStore(Path(folder.name) / "bot.sqlite3")
        self.store.command("app", "group", "member", "message", f"绑定 {STEAM}")
        with self.store.transaction() as db:
            self.request_id = db.execute("SELECT request_id FROM bindings").fetchone()[0]
        self.server = create_server("https://bot.example.com", 0, self.store)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_public_address_must_be_https_root(self):
        for address in ("http://bot.example.com", "https://bot.example.com/x",
                        "https://x:y@bot.example.com", "https://bot.example.com/?x=1"):
            with self.assertRaises(ValueError):
                checked_public_url(address)

    @patch("qq_cs2_bot.openid_remote.configured_public_url", return_value="https://bot.example.com")
    def test_only_pending_request_has_link(self, configured):
        self.assertEqual(link_for_request(self.request_id, self.store),
                         "https://bot.example.com/verify/" + self.request_id)
        self.store.approve(self.request_id, STEAM)
        self.assertIsNone(link_for_request(self.request_id, self.store))

    @patch("qq_cs2_bot.openid_remote.verified_steam_id", return_value=STEAM)
    def test_verified_owner_approves_once(self, verify):
        opener = build_opener(NoRedirect())
        try:
            opener.open(self.base + "/verify/" + self.request_id)
        except HTTPError as response:
            self.assertEqual(response.code, 302)
            steam_url = response.headers["Location"]
            response.close()
        callback = parse_qs(urlsplit(steam_url).query)["openid.return_to"][0]
        state = parse_qs(urlsplit(callback).query)["state"][0]
        with opener.open(self.base + "/steam/callback?state=" + state) as response:
            self.assertIn("验证成功", response.read().decode())
        verify.assert_called_once_with("state=" + state, callback)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT status FROM bindings").fetchone()[0], "verified")
        with self.assertRaises(HTTPError) as replay:
            opener.open(self.base + "/steam/callback?state=" + state)
        self.assertEqual(replay.exception.code, 400)
        replay.exception.close()

    def test_wrong_host_is_rejected(self):
        # The service only accepts its configured tunnel host or loopback probes.
        with self.assertRaises(HTTPError) as error:
            build_opener().open(self.base.replace("127.0.0.1", "localhost") + "/health")
        self.assertEqual(error.exception.code, 421)
        error.exception.close()

    @patch("qq_cs2_bot.openid_remote.verified_steam_id", return_value="76561199353160602")
    def test_other_steam_account_cannot_claim_binding(self, verify):
        opener = build_opener(NoRedirect())
        try:
            opener.open(self.base + "/verify/" + self.request_id)
        except HTTPError as response:
            steam_url = response.headers["Location"]
            response.close()
        callback = parse_qs(urlsplit(steam_url).query)["openid.return_to"][0]
        state = parse_qs(urlsplit(callback).query)["state"][0]
        with self.assertRaises(HTTPError) as error:
            opener.open(self.base + "/steam/callback?state=" + state)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT status FROM bindings").fetchone()[0], "pending")


if __name__ == "__main__":
    unittest.main()
