import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qq_cs2_bot.bindings import BindingStore, valid_steam_id
from qq_cs2_bot.binding_commands import reply_to_binding
from qq_cs2_bot.qq_check import CheckError

STEAM = "76561199117265694"
OTHER = "76561199353160602"


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "db.sqlite3"
        self.store = BindingStore(self.path)
        self.n = 0

    def command(self, text, member="member-a", group="group-a", app="app-a"):
        self.n += 1
        return self.store.command(app, group, member, f"msg-{self.n}", text)

    def record(self, member="member-a"):
        with self.store.transaction() as db:
            return db.execute("SELECT * FROM bindings WHERE member=?", (member,)).fetchone()

    @patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"})
    def test_panel_slash_commands_reach_existing_handler(self, request):
        def incoming(content, message_id):
            return {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {
                "content": content, "group_openid": "group-a", "id": message_id,
                "author": {"member_openid": "member-a"}}}
        self.assertTrue(reply_to_binding(incoming("<@123> /帮助", "help"), "token", "app-a", self.store))
        help_text = request.call_args.kwargs["payload"]["content"]
        self.assertIn("指令帮助", help_text)
        self.assertIn("/我的比赛 9", help_text)
        self.assertIn("/我的比赛列表 2", help_text)
        self.assertIn("/9", help_text)
        self.assertIn("/个人播报 开", help_text)
        self.assertIn("群管理员身份不会自动取得此权限", help_text)
        self.assertTrue(reply_to_binding(incoming("<@123> /我的绑定", "binding"), "token", "app-a", self.store))
        self.assertIn("尚未绑定", request.call_args.kwargs["payload"]["content"])

    @patch("qq_cs2_bot.binding_commands.qq_link_enabled", return_value=True)
    @patch("qq_cs2_bot.binding_commands.configured_public_url", return_value="https://bot.example.com")
    @patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"})
    def test_pending_binding_includes_remote_verification_link(self, request, configured, enabled):
        incoming = {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {
            "content": f"<@123> 绑定 {STEAM}", "group_openid": "group-a",
            "id": "remote-bind", "author": {"member_openid": "member-a"}}}
        self.assertTrue(reply_to_binding(incoming, "token", "app-a", self.store))
        binding = self.store.get_binding("app-a", "group-a", "member-a")
        self.assertIn("https://bot.example.com/verify/" + binding["request_id"],
                      request.call_args.kwargs["payload"]["content"])

    def test_pending_persists_and_requires_approval(self):
        reply = self.command(f"绑定 {STEAM}")
        self.assertIn("待验证", reply)
        self.assertTrue(reply.endswith("发送“#绑定链接 你的申请编号”以获得绑定链接。"))
        self.assertTrue(self.command(f"绑定 {STEAM}").endswith(
            "发送“#绑定链接 你的申请编号”以获得绑定链接。"))
        self.store = BindingStore(self.path)
        self.assertIn("待验证", self.command("我的绑定"))
        request = self.record()["request_id"]
        self.store.approve(request, STEAM)
        self.assertIn("已验证", self.command("我的绑定"))

    def test_member_group_and_app_isolation(self):
        self.command(f"绑定 {STEAM}")
        self.assertIn("尚未绑定", self.command("我的绑定", member="member-b"))
        self.assertIn("尚未绑定", self.command("我的绑定", group="group-b"))
        self.assertIn("尚未绑定", self.command("我的绑定", app="app-b"))
        self.command("解绑", member="member-b")
        self.assertIsNotNone(self.record())

    def test_unbind_deletes_and_old_approval_fails(self):
        self.command(f"绑定 {STEAM}")
        old = self.record()["request_id"]
        self.command("解绑")
        self.assertIsNone(self.record())
        self.command(f"绑定 {STEAM}")
        self.assertNotEqual(old, self.record()["request_id"])
        with self.assertRaises(ValueError):
            self.store.approve(old, STEAM)

    def test_replayed_bind_does_not_recreate_after_unbind(self):
        self.store.command("a", "g", "m", "old", f"绑定 {STEAM}")
        self.store.command("a", "g", "m", "new", "解绑")
        reopened = BindingStore(self.path)
        self.assertIsNone(reopened.command("a", "g", "m", "old", f"绑定 {STEAM}"))
        self.assertIn("尚未绑定", reopened.command("a", "g", "m", "status", "我的绑定"))

    def test_pending_does_not_reserve_another_persons_account(self):
        self.command(f"绑定 {STEAM}")
        self.command(f"绑定 {STEAM}", member="member-b")
        self.store.approve(self.record("member-b")["request_id"], STEAM)
        with self.assertRaises(ValueError):
            self.store.approve(self.record()["request_id"], STEAM)

    def test_cannot_replace_verified_account(self):
        self.command(f"绑定 {STEAM}")
        self.store.approve(self.record()["request_id"], STEAM)
        self.assertIn("先发送", self.command(f"绑定 {OTHER}"))
        self.assertEqual(self.record()["steam_id"], STEAM)
        self.assertEqual(self.record()["status"], "verified")

    def test_invalid_ids_and_targeted_unbind(self):
        for value in ("123", "9219329326884564108", "00000000000000000", "76561199117265694 extra"):
            self.assertIn("格式", self.command(f"绑定 {value}"))
        self.command(f"#绑定 {STEAM}")
        self.assertIn("仅解除自己", self.command("解绑 member-a"))
        self.assertIsNotNone(self.record())
        self.assertTrue(valid_steam_id(STEAM))

    def test_approval_requires_exact_account(self):
        self.command(f"绑定 {STEAM}")
        with self.assertRaises(ValueError):
            self.store.approve(self.record()["request_id"], OTHER)
        self.assertEqual(self.record()["status"], "pending")

    @patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"})
    def test_event_identity_and_persistent_duplicate(self, send):
        event = {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {
            "id": "event1", "content": f"<@123> 绑定 {STEAM}", "group_openid": "group-a",
            "author": {"member_openid": "member-a"}}}
        self.assertTrue(reply_to_binding(event, "fake", "app-a", self.store))
        self.assertFalse(reply_to_binding(event, "fake", "app-a", BindingStore(self.path)))
        send.assert_called_once()
        self.assertEqual(self.record()["steam_id"], STEAM)

    @patch("qq_cs2_bot.binding_commands.request_json", side_effect=CheckError("timeout"))
    def test_send_failure_preserves_committed_state(self, send):
        event = {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {
            "id": "event1", "content": f"绑定 {STEAM}", "group_openid": "group-a",
            "author": {"member_openid": "member-a"}}}
        with self.assertRaises(CheckError):
            reply_to_binding(event, "fake", "app-a", self.store)
        self.assertIn("待验证", self.command("我的绑定"))

    @patch("qq_cs2_bot.binding_commands.request_json")
    def test_missing_trusted_identity_is_ignored(self, send):
        event = {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {
            "id": "event1", "content": f"绑定 {STEAM}", "group_openid": "group-a",
            "author": {"id": "not-member-openid"}}}
        self.assertFalse(reply_to_binding(event, "fake", "app-a", self.store))
        self.assertIsNone(self.record())
        send.assert_not_called()
