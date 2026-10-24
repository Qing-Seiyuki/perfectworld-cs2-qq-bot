import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qq_cs2_bot.qq_check import CheckError, check_connection, credentials


class QQCheckTests(unittest.TestCase):
    def test_missing_config(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CheckError):
                credentials(Path(folder) / ".env")

    def test_local_config_and_env_override(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            path = Path(folder) / ".env"
            path.write_text('QQ_APP_ID=123\nQQ_APP_SECRET="fake=a"\n', encoding="utf-8-sig")
            self.assertEqual(credentials(path), ("123", "fake=a"))
            with patch.dict(os.environ, {"QQ_APP_SECRET": "override"}):
                self.assertEqual(credentials(path), ("123", "override"))

    @patch("qq_cs2_bot.qq_check.request_json")
    def test_auth_then_gateway_only(self, request):
        request.side_effect = [{"access_token": "test-token"}, {"url": "wss://api.bot.qq.com/websocket/"}]
        check_connection("123", "fake")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.args, ("/gateway",))
        self.assertEqual(request.call_args.kwargs, {"token": "test-token"})

    @patch("qq_cs2_bot.qq_check.request_json", return_value={"code": 100016})
    def test_no_token_stops_before_gateway(self, request):
        with self.assertRaises(CheckError):
            check_connection("123", "fake")
        self.assertEqual(request.call_count, 1)
