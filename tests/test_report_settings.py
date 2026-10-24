import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from qq_cs2_bot.bindings import BindingStore

STEAM = "76561199117265694"


class ReportSettingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "state.sqlite3"
        self.store = BindingStore(self.path)
        self.n = 0

    def command(self, text, member="m", group="g"):
        self.n += 1
        return self.store.command("a", group, member, f"message-{self.n}", text)

    def bind_verified(self):
        self.command(f"绑定 {STEAM}")
        self.store.approve(self.store.get_binding("a", "g", "m")["request_id"], STEAM)

    def test_default_off_and_requires_verified_binding(self):
        self.assertIn("我的比赛自动播报：关", self.command("播报 状态"))
        self.assertIn("本群自动播报总开关：关", self.command("播报 状态"))
        self.assertIn("先完成", self.command("播报 开"))
        self.command(f"绑定 {STEAM}")
        self.assertIn("先完成", self.command("播报 开"))
        self.assertEqual(self.store.eligible_members("a", "g"), [])

    def test_both_switches_gate_future_monitor(self):
        self.bind_verified()
        self.command("播报 开")
        self.assertEqual(self.store.eligible_members("a", "g"), [])
        self.store.set_group_report_enabled("a", "g", True)
        self.assertEqual(len(self.store.eligible_members("a", "g")), 1)
        self.assertEqual(self.store.eligible_members("a", "g")[0]["steam_id"], STEAM)
        self.command("播报 关")
        self.assertEqual(self.store.eligible_members("a", "g"), [])
        self.command("播报 开")
        self.store.set_group_report_enabled("a", "g", False)
        self.assertEqual(self.store.eligible_members("a", "g"), [])

    def test_unbind_clears_opt_in_but_group_setting_persists(self):
        self.bind_verified()
        self.command("播报 开")
        self.store.set_group_report_enabled("a", "g", True)
        self.command("解绑")
        self.assertEqual(self.store.eligible_members("a", "g"), [])
        self.assertIn("我的比赛自动播报：关", self.command("播报 状态"))
        self.assertIn("本群自动播报总开关：开", self.command("播报 状态"))
        self.command(f"绑定 {STEAM}")
        self.store.approve(self.store.get_binding("a", "g", "m")["request_id"], STEAM)
        self.assertEqual(self.store.eligible_members("a", "g"), [])

    def test_personal_and_group_switches_are_independent(self):
        self.bind_verified()
        self.store.set_group_report_enabled("a", "g", True)
        self.assertIn("总开关仍为：开（未更改）", self.command("个人播报 关"))
        self.assertIn("我的比赛自动播报：关", self.command("播报 状态"))
        self.assertIn("本群自动播报总开关：开", self.command("群播报 状态"))
        self.assertIn("总开关仍为：开（未更改）", self.command("个人播报 开"))
        self.assertEqual(len(self.store.eligible_members("a", "g")), 1)
        self.assertIn("不能通过群消息修改", self.command("群播报 关"))
        self.assertIn("本群自动播报总开关：开", self.command("群播报 状态"))
        self.store.set_group_report_enabled("a", "g", False)
        self.assertIn("我的比赛自动播报：开", self.command("播报 状态"))
        self.assertIn("本群自动播报总开关：关", self.command("播报 状态"))
        self.assertEqual(self.store.eligible_members("a", "g"), [])

    def test_group_app_isolation_and_restart(self):
        self.bind_verified()
        self.command("播报 开")
        self.store.set_group_report_enabled("a", "g", True)
        self.store = BindingStore(self.path)
        self.assertEqual(len(self.store.eligible_members("a", "g")), 1)
        self.assertEqual(self.store.eligible_members("a", "other"), [])
        self.assertEqual(self.store.eligible_members("other", "g"), [])

    def test_migrate_v2_and_repeat(self):
        path = self.path.with_name("old.sqlite3")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""CREATE TABLE bindings(app TEXT,group_id TEXT,member TEXT,request_id TEXT UNIQUE,
                steam_id TEXT,status TEXT,created_at TEXT,verified_at TEXT,display_name TEXT,challenge TEXT,
                challenge_expires INTEGER,last_check INTEGER,PRIMARY KEY(app,group_id,member))""")
            db.execute("PRAGMA user_version=2")
        BindingStore(path)
        BindingStore(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
