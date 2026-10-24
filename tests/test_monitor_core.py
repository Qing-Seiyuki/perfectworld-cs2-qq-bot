import tempfile
import unittest
from pathlib import Path

from qq_cs2_bot.bindings import BindingStore
from qq_cs2_bot.monitor_core import can_deliver, prepare_team_report
from qq_cs2_bot.report import IncompleteMatch
from test_report import fixture

FIRST = "76561199117265694"
SECOND = "76561199353160602"


class MonitorCoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "state.sqlite3"
        self.store = BindingStore(self.path)
        self.detail = fixture()
        self.detail["data"]["players"][8]["playerId"] = FIRST
        self.detail["data"]["players"][7]["playerId"] = SECOND
        self.match_id = self.detail["data"]["base"]["matchId"]

    def subscribe(self, group="g", member="m", steam=FIRST, app="a"):
        self.store.command(app, group, member, f"bind-{group}-{member}", f"绑定 {steam}")
        record = self.store.get_binding(app, group, member)
        self.store.approve(record["request_id"], steam)
        self.store.command(app, group, member, f"opt-{group}-{member}", "播报 开")
        self.store.set_group_report_enabled(app, group, True)

    def test_five_stack_one_report_survives_restart(self):
        self.subscribe()
        self.subscribe(member="friend", steam=SECOND)
        first = prepare_team_report(self.store, "a", "g", self.detail)
        self.assertTrue(first.newly_queued)
        self.assertIn("我方 13∶10", first.text)
        self.assertEqual(first.text.count("QQ："), 5)
        restarted = BindingStore(self.path)
        again = prepare_team_report(restarted, "a", "g", self.detail)
        self.assertFalse(again.newly_queued)
        with restarted.transaction() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM report_deliveries").fetchone()[0], 1)

    def test_switches_gate_queue_and_delivery(self):
        self.subscribe()
        self.store.set_group_report_enabled("a", "g", False)
        self.assertIsNone(prepare_team_report(self.store, "a", "g", self.detail))
        self.store.set_group_report_enabled("a", "g", True)
        prepare_team_report(self.store, "a", "g", self.detail)
        self.assertTrue(can_deliver(self.store, "a", "g", self.match_id))
        self.store.command("a", "g", "m", "off", "播报 关")
        self.assertFalse(can_deliver(self.store, "a", "g", self.match_id))
        self.store.command("a", "g", "m", "unbind", "解绑")
        self.assertFalse(can_deliver(self.store, "a", "g", self.match_id))

    def test_group_isolation(self):
        self.subscribe(group="g")
        self.subscribe(group="other", member="other")
        self.assertTrue(prepare_team_report(self.store, "a", "g", self.detail).newly_queued)
        self.assertTrue(prepare_team_report(self.store, "a", "other", self.detail).newly_queued)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM report_deliveries").fetchone()[0], 2)

    def test_opposing_subscribers_do_not_mislabel_our_team(self):
        self.subscribe()
        self.detail["data"]["players"][0]["playerId"] = SECOND
        self.subscribe(member="opponent", steam=SECOND)
        with self.assertRaises(IncompleteMatch):
            prepare_team_report(self.store, "a", "g", self.detail)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM report_deliveries").fetchone()[0], 0)

    def test_incomplete_detail_never_queued(self):
        self.subscribe()
        self.detail["data"]["players"].pop()
        with self.assertRaises(IncompleteMatch):
            prepare_team_report(self.store, "a", "g", self.detail)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM report_deliveries").fetchone()[0], 0)

    def test_absent_subscriber_no_report(self):
        self.subscribe()
        self.detail["data"]["players"][8]["playerId"] = "unbound-id"
        self.assertIsNone(prepare_team_report(self.store, "a", "g", self.detail))
