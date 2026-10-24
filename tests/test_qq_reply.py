import unittest
from unittest.mock import patch

from qq_cs2_bot.qq_check import CheckError
from qq_cs2_bot.qq_reply import reply_to_test
from test_report import fixture


def event(content="测试"):
    return {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {
        "content": content, "group_openid": "group-test", "id": "message-test"}}


class ReplyTests(unittest.TestCase):
    @patch("qq_cs2_bot.qq_reply.request_json", return_value={"id": "reply-test"})
    def test_reply_and_duplicate(self, request):
        attempted = set()
        self.assertTrue(reply_to_test(event(" <@123> 测试 "), "fake-token", attempted))
        self.assertFalse(reply_to_test(event(), "fake-token", attempted))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["payload"]["msg_id"], "message-test")

    @patch("qq_cs2_bot.qq_reply.request_json")
    def test_other_messages_ignored(self, request):
        for content in ("你好", "测试一下", "", "请发送测试"):
            self.assertFalse(reply_to_test(event(content), "fake-token", set()))
        other = event()
        other["t"] = "C2C_MESSAGE_CREATE"
        self.assertFalse(reply_to_test(other, "fake-token", set()))
        request.assert_not_called()

    @patch("qq_cs2_bot.qq_reply.request_json", side_effect=CheckError("timeout"))
    def test_ambiguous_delivery_is_not_retried(self, request):
        attempted = set()
        with self.assertRaises(CheckError):
            reply_to_test(event(), "fake-token", attempted)
        self.assertFalse(reply_to_test(event(), "fake-token", attempted))
        self.assertEqual(request.call_count, 1)

    @patch("qq_cs2_bot.qq_reply.request_json", return_value={})
    def test_receipt_required(self, request):
        with self.assertRaises(CheckError):
            reply_to_test(event(), "fake-token", set())

    @patch("qq_cs2_bot.qq_reply.request_json", return_value={"id": "reply-report"})
    @patch("qq_cs2_bot.qq_reply.fetch_detail")
    def test_real_report_pipeline_and_default_rating(self, fetch, request):
        data = fixture()
        data["data"]["players"][8]["playerId"] = "76561199117265694"
        fetch.return_value = data
        incoming = event("战报 1234567890123456789 76561199117265694")
        attempted = set()
        self.assertTrue(reply_to_test(incoming, "fake-token", attempted, report_mode=True))
        body = request.call_args.kwargs["payload"]
        self.assertIn("完美 Rating", body["content"])
        self.assertIn("我方 13∶10", body["content"])
        self.assertEqual(body["content"].count("QQ：未绑定"), 5)
        self.assertFalse(reply_to_test(incoming, "fake-token", attempted, report_mode=True))
        fetch.assert_called_once_with("1234567890123456789")

    @patch("qq_cs2_bot.qq_reply.request_json", return_value={"id": "error-reply"})
    @patch("qq_cs2_bot.qq_reply.fetch_detail", side_effect=ValueError("private upstream details"))
    def test_provider_failure_is_not_fabricated(self, fetch, request):
        reply_to_test(event("战报 1234567890123456789 76561199117265694"), "fake-token", set(), report_mode=True)
        content = request.call_args.kwargs["payload"]["content"]
        self.assertIn("暂时无法", content)
        self.assertNotIn("private", content)

    @patch("qq_cs2_bot.qq_reply.fetch_detail")
    def test_report_requires_explicit_ids(self, fetch):
        for content in ("战报", "战报 123", "测试"):
            self.assertFalse(reply_to_test(event(content), "fake-token", set(), report_mode=True))
        fetch.assert_not_called()
