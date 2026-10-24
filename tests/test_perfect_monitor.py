import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from qq_cs2_bot.bindings import BindingStore
from qq_cs2_bot.napcat_sender import SendError
from qq_cs2_bot.perfect_monitor import ReportMonitor
from test_report import fixture

STEAM = "76561199117265694"
OTHER = "76561199353160602"


class PerfectMonitorTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = BindingStore(Path(folder.name) / "state.sqlite3")
        self.monitor = ReportMonitor(self.store)
        self.monitor.set_route("app", "openid", "1020431073")
        self.store.set_group_report_enabled("app", "openid", True)
        self.subscribe("member", STEAM)
        self.detail = fixture()
        self.detail["data"]["players"][8]["playerId"] = STEAM
        self.match_id = self.detail["data"]["base"]["matchId"]
        self.ended = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.rows = [{"matchId": self.match_id, "endTime": self.ended}]
        self.sent = []

    def subscribe(self, member, steam):
        self.store.command("app", "openid", member, "bind-" + member, "绑定 " + steam)
        self.store.approve(self.store.get_binding("app", "openid", member)["request_id"], steam)
        self.store.command("app", "openid", member, "on-" + member, "播报 开")

    def recent(self, steam, *, limit):
        self.assertEqual(limit, 10)
        return self.rows

    def sender(self, group, text, *, access_token, port):
        self.sent.append((group, text))
        return str(len(self.sent))

    def poll(self, *, detail=None, sender=None):
        return self.monitor.poll_once("secret", 3000, recent=self.recent,
                                      detail=detail or (lambda _: self.detail),
                                      sender=sender or self.sender)

    def test_baseline_then_one_new_match_only(self):
        self.assertEqual(self.poll(), 0)
        self.assertEqual(self.sent, [])
        self.detail["data"]["base"]["matchId"] = "PVP@9219329326884564109"
        self.rows = [{"matchId": "PVP@9219329326884564109", "endTime": self.ended}]
        self.assertEqual(self.poll(), 1)
        self.assertEqual(self.sent[0][0], "1020431073")
        self.assertIn("完美 Rating", self.sent[0][1])
        self.assertEqual(self.poll(), 0)
        self.monitor = ReportMonitor(BindingStore(self.store.path))
        self.assertEqual(self.poll(), 0)

    def test_incomplete_detail_waits_then_sends(self):
        self.poll()
        self.rows = [{"matchId": "PVP@9219329326884564110", "endTime": self.ended}]
        self.detail["data"]["base"]["matchId"] = self.rows[0]["matchId"]
        broken = deepcopy(self.detail)
        broken["data"]["players"].pop(7)
        self.assertEqual(self.poll(detail=lambda _: broken), 0)
        self.assertEqual(self.poll(), 1)

    def test_two_teammates_one_report(self):
        self.subscribe("friend", OTHER)
        self.detail["data"]["players"][7]["playerId"] = OTHER
        self.poll()
        self.detail["data"]["base"]["matchId"] = "PVP@9219329326884564111"
        self.rows = [{"matchId": self.detail["data"]["base"]["matchId"], "endTime": self.ended}]
        self.assertEqual(self.poll(), 1)
        self.assertEqual(len(self.sent), 1)

    def test_ambiguous_send_is_not_retried(self):
        self.poll()
        self.detail["data"]["base"]["matchId"] = "PVP@9219329326884564112"
        self.rows = [{"matchId": self.detail["data"]["base"]["matchId"], "endTime": self.ended}]
        def fail(*args, **kwargs):
            raise SendError("unknown")
        self.assertEqual(self.poll(sender=fail), 0)
        self.assertEqual(self.poll(), 0)
        with self.store.transaction() as db:
            row = db.execute("SELECT status FROM report_deliveries").fetchone()
            self.assertEqual(row[0], "unknown")

    def test_opt_out_prevents_old_matches_after_opt_in_again(self):
        self.poll()
        self.store.command("app", "openid", "member", "off", "播报 关")
        self.detail["data"]["base"]["matchId"] = "PVP@9219329326884564113"
        self.rows = [{"matchId": self.detail["data"]["base"]["matchId"], "endTime": self.ended}]
        self.assertEqual(self.poll(), 0)
        self.store.command("app", "openid", "member", "on-again", "播报 开")
        self.assertEqual(self.poll(), 0)

    def test_stale_match_after_restart_is_not_pushed(self):
        self.poll()
        self.detail["data"]["base"]["matchId"] = "PVP@9219329326884564114"
        stale = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        self.rows = [{"matchId": self.detail["data"]["base"]["matchId"], "endTime": stale}]
        self.monitor = ReportMonitor(BindingStore(self.store.path))
        self.assertEqual(self.poll(), 0)

    def test_group_switch_prevents_discovery(self):
        self.poll()
        self.store.set_group_report_enabled("app", "openid", False)
        self.detail["data"]["base"]["matchId"] = "PVP@9219329326884564115"
        self.rows = [{"matchId": self.detail["data"]["base"]["matchId"], "endTime": self.ended}]
        self.assertEqual(self.poll(), 0)
        self.store.set_group_report_enabled("app", "openid", True)
        self.assertEqual(self.poll(), 0)


if __name__ == "__main__":
    unittest.main()
