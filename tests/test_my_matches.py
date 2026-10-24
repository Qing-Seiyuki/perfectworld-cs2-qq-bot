import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qq_cs2_bot.binding_commands import reply_to_binding
from qq_cs2_bot.bindings import BindingStore
from qq_cs2_bot.my_matches import render_match_list
from test_report import fixture

STEAM = "76561199117265694"
FIRST = "PVP@9219329326884564108"
NINTH = "PVP@9219329326884564109"


def event(message, text, member="member"):
    return {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {
        "id": message, "content": "<@123> " + text, "group_openid": "group",
        "author": {"member_openid": member}}}


def row(match_id):
    return {"playerId": STEAM, "matchId": match_id, "endTime": "2026-10-24 02:00:00",
            "mapName": "炙热沙城Ⅱ", "team": 2, "score1": 10, "score2": 13,
            "kill": 21, "death": 15, "pwRating": 1.32}


class MyMatchesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = BindingStore(Path(folder.name) / "db.sqlite3")
        self.store.command("app", "group", "member", "bind", "绑定 " + STEAM)
        self.store.approve(self.store.get_binding("app", "group", "member")["request_id"], STEAM)
        self.send = self.enterContext(patch("qq_cs2_bot.binding_commands.request_json", return_value={"id": "reply"}))
        self.page = self.enterContext(patch("qq_cs2_bot.binding_commands.fetch_match_page"))
        self.detail = self.enterContext(patch("qq_cs2_bot.binding_commands.fetch_detail"))
        result = fixture()
        result["data"]["players"][8]["playerId"] = STEAM
        self.detail.return_value = result

    def reply(self, message, text, member="member"):
        reply_to_binding(event(message, text, member), "token", "app", self.store)
        return self.send.call_args.kwargs["payload"]["content"]

    def test_default_one_and_number_selection(self):
        self.page.return_value = [row(FIRST)]
        response = self.reply("m1", "/我的比赛")
        self.assertIn("【完美 CS2 战报】", response)
        self.assertIn("完美 Rating", response)
        self.page.assert_called_with(STEAM, 1)
        self.detail.assert_called_with(FIRST)
        self.detail.reset_mock()
        self.page.return_value = [row(NINTH)]
        self.reply("m2", "/9")
        self.page.assert_called_with(STEAM, 2)
        self.detail.assert_called_with(NINTH)
        self.reply("m3", "/我的比赛 9")
        self.page.assert_called_with(STEAM, 2)
        self.detail.assert_called_with(NINTH)

    def test_list_pages_are_compact_and_use_absolute_numbers(self):
        self.page.return_value = [row(FIRST)] * 8
        first = self.reply("list1", "/我的比赛列表")
        self.assertIn("1. 2026-10-24", first)
        self.assertIn("8. 2026-10-24", first)
        self.assertIn("/我的比赛列表 2", first)
        self.assertNotIn("击杀", first)
        self.assertNotIn("Rating", first)
        self.detail.assert_not_called()
        self.page.return_value = [row(NINTH)]
        second = self.reply("list2", "/我的比赛列表 2")
        self.page.assert_called_with(STEAM, 2)
        self.assertIn("9. 2026-10-24", second)
        self.assertNotIn("/我的比赛列表 3", second)

    def test_only_verified_sender_can_query(self):
        response = self.reply("other", "/我的比赛", member="stranger")
        self.assertIn("先在本群绑定并验证", response)
        self.page.assert_not_called()
        self.detail.assert_not_called()

    def test_unavailable_page_and_invalid_selection(self):
        self.page.return_value = None
        self.assertIn("暂不可查", self.reply("bad-source", "/我的比赛列表"))
        self.page.return_value = []
        self.assertIn("没有找到这个序号", self.reply("missing", "/我的比赛 9"))
        self.detail.assert_not_called()
        self.page.reset_mock()
        self.assertIn("请发送", self.reply("bad-number", "/我的比赛 0"))
        self.page.assert_not_called()

    def test_recheck_binding_after_network_fetch(self):
        def unbind_then_return(*args, **kwargs):
            self.store.command("app", "group", "member", "unbind", "解绑")
            return [row(FIRST)]
        self.page.side_effect = unbind_then_return
        response = self.reply("changed", "/我的比赛")
        self.assertIn("绑定状态已变更", response)
        self.detail.assert_not_called()

    def test_list_text_cleans_untrusted_fields(self):
        item = row(FIRST)
        item["mapName"] = "地图\n伪造行"
        output = render_match_list([item], 1)
        self.assertIn("地图 伪造行", output)
        self.assertNotIn("地图\n伪造行", output)


if __name__ == "__main__":
    unittest.main()
