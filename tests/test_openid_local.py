import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from qq_cs2_bot.bindings import BindingStore
from qq_cs2_bot.openid_local import OPENID_NS, STEAM_ENDPOINT, OpenIDError, login_url, verified_steam_id

STEAM = "76561199117265694"
RETURN_TO = "http://127.0.0.1:8765/steam/callback?state=test-state"
CLAIMED = f"https://steamcommunity.com/openid/id/{STEAM}"


def assertion(**overrides):
    params = {"openid.ns": OPENID_NS, "openid.mode": "id_res",
              "openid.op_endpoint": STEAM_ENDPOINT, "openid.return_to": RETURN_TO,
              "openid.claimed_id": CLAIMED, "openid.identity": CLAIMED,
              "openid.response_nonce": "2026-10-23T00:00:00Ztest", "openid.assoc_handle": "test",
              "openid.signed": "return_to,claimed_id,identity,response_nonce,assoc_handle,op_endpoint",
              "openid.sig": "test-signature"}
    params.update(overrides)
    from urllib.parse import urlencode
    return urlencode(params)


def fake_opener(response=b"ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"):
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(return_value=None)
    stream.read.return_value = response
    opener = Mock()
    opener.open.return_value = stream
    return opener


class OpenIDTests(unittest.TestCase):
    def test_login_url_targets_steam_and_local_callback(self):
        url = login_url(RETURN_TO, "http://127.0.0.1:8765/")
        self.assertEqual(urlsplit(url).netloc, "steamcommunity.com")
        self.assertEqual(parse_qs(urlsplit(url).query)["openid.return_to"], [RETURN_TO])

    def test_valid_signature_is_checked_with_steam(self):
        opener = fake_opener()
        self.assertEqual(verified_steam_id(assertion(), RETURN_TO, opener=opener), STEAM)
        sent = opener.open.call_args.args[0]
        self.assertEqual(sent.full_url, STEAM_ENDPOINT)
        self.assertIn(b"check_authentication", sent.data)

    def test_forged_browser_return_is_rejected(self):
        for query in (assertion(**{"openid.sig": ""}),
                      assertion(**{"openid.return_to": "http://evil.invalid/"}),
                      assertion(**{"openid.op_endpoint": "https://evil.invalid/login"}),
                      assertion(**{"openid.identity": "https://steamcommunity.com/openid/id/76561199353160602"}),
                      assertion() + "&openid.claimed_id=duplicate"):
            opener = fake_opener()
            with self.assertRaises(OpenIDError):
                verified_steam_id(query, RETURN_TO, opener=opener)
            opener.open.assert_not_called()

    def test_steam_rejects_assertion(self):
        with self.assertRaises(OpenIDError):
            verified_steam_id(assertion(), RETURN_TO, opener=fake_opener(b"is_valid:false\n"))

    def test_approval_only_after_verified_matching_steam_id(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BindingStore(Path(folder) / "state.sqlite3")
            store.command("a", "g", "m", "bind", f"绑定 {STEAM}")
            row = store.get_binding("a", "g", "m")
            with self.assertRaises(OpenIDError):
                verified_steam_id(assertion(), RETURN_TO, opener=fake_opener(b"is_valid:false\n"))
            self.assertEqual(store.get_binding("a", "g", "m")["status"], "pending")
            claimed = verified_steam_id(assertion(), RETURN_TO, opener=fake_opener())
            self.assertEqual(claimed, row["steam_id"])
            store.approve(row["request_id"], claimed)
            self.assertEqual(store.get_binding("a", "g", "m")["status"], "verified")
