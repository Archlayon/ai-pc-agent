"""
Basic tests for the AI PC Agent core modules.
"""
import os
import tempfile
import unittest

from tool_registry import dispatch, get_declarations, TOOLS
from audit_log import log_action, get_recent
from memory import append_message, get_context, prune_old
from registry import register_module, is_module_approved, load_registry
from settings import get_settings, update_settings
from tools.folder_watch import add_folder_watch, list_folder_watches, remove_folder_watch
from tools.email_tools import draft_email, list_drafts
from tools.edit_tools import append_file, edit_file_line, read_file, write_file
from tools.monitor_tools import get_battery_status, get_cpu_usage, get_disk_usage, get_full_pc_state, get_memory_usage
from tools.system_tools import cancel_shutdown, get_brightness, get_volume, restart_pc, set_brightness, set_volume, shutdown_pc
from tools.research_tools import list_reports, research_topic
from consent import CONSENT_COPY, request_consent


class TestToolRegistry(unittest.TestCase):
    def test_get_declarations(self):
        decls = get_declarations()
        self.assertTrue(len(decls) > 0)
        names = [d["name"] for d in decls]
        self.assertIn("open_app", names)
        self.assertIn("move_file", names)
        self.assertIn("set_brightness", names)
        self.assertIn("draft_email", names)
        self.assertIn("read_file", names)
        self.assertIn("write_file", names)
        self.assertIn("shutdown_pc", names)
        self.assertIn("restart_pc", names)
        self.assertIn("get_cpu_usage", names)
        self.assertIn("research_topic", names)

    def test_dispatch_unknown(self):
        result = dispatch("nonexistent_tool", {})
        self.assertIn("error", result.lower())

    def test_open_app_missing(self):
        result = dispatch("open_app", {"app_name": "nonexistent_app_xyz"})
        self.assertIn("error", result.lower())

    def test_safe_tools_exist(self):
        self.assertIn("get_volume", TOOLS)
        self.assertIn("list_drafts", TOOLS)
        self.assertIn("list_folder_watches", TOOLS)
        self.assertIn("read_file", TOOLS)
        self.assertIn("get_full_pc_state", TOOLS)


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        import audit_log
        self.orig_path = audit_log.DB_PATH
        audit_log.DB_PATH = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        import audit_log
        audit_log.DB_PATH = self.orig_path

    def test_log_and_retrieve(self):
        log_action("open_app", {"app_name": "firefox"}, "approved", "Launched firefox")
        rows = get_recent(10)
        self.assertTrue(len(rows) >= 1)
        self.assertEqual(rows[0]["tool_name"], "open_app")
        self.assertEqual(rows[0]["decision"], "approved")


class TestMemory(unittest.TestCase):
    def setUp(self):
        import memory
        self.orig_path = memory.DB_PATH
        memory.DB_PATH = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        import memory
        memory.DB_PATH = self.orig_path

    def test_append_and_context(self):
        append_message("s1", "user", "hello")
        append_message("s1", "assistant", "hi there")
        ctx = get_context("s1")
        self.assertEqual(len(ctx), 2)
        self.assertEqual(ctx[0]["role"], "user")
        self.assertEqual(ctx[0]["content"], "hello")

    def test_prune(self):
        for i in range(30):
            append_message("s1", "user", f"msg {i}")
        prune_old("s1", keep=10)
        ctx = get_context("s1", limit=100)
        self.assertTrue(len(ctx) <= 10)


class TestRegistry(unittest.TestCase):
    def setUp(self):
        import registry
        self.orig_path = registry.REGISTRY_PATH
        registry.REGISTRY_PATH = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        import registry
        registry.REGISTRY_PATH = self.orig_path

    def test_register_and_check(self):
        m = register_module("test_mod", "A test", "/tmp/test.py", approved=True)
        self.assertTrue(is_module_approved("test_mod"))


class TestSettings(unittest.TestCase):
    def test_defaults(self):
        s = get_settings()
        self.assertIn("autonomy_mode", s)
        self.assertIn("hotkey", s)
        self.assertIn("gui_confirm", s)

    def test_update(self):
        update_settings({"autonomy_mode": True})
        s = get_settings()
        self.assertTrue(s["autonomy_mode"])
        update_settings({"autonomy_mode": False})


class TestFolderWatch(unittest.TestCase):
    def setUp(self):
        import tools.folder_watch as fw
        self.orig_path = fw.WATCH_STATE_PATH
        fw.WATCH_STATE_PATH = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        import tools.folder_watch as fw
        fw.WATCH_STATE_PATH = self.orig_path

    def test_add_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = add_folder_watch(tmpdir, "notify")
            self.assertIn("Watching", result)
            watches = list_folder_watches()
            self.assertIn(tmpdir, watches)


class TestEmailTools(unittest.TestCase):
    def setUp(self):
        import tools.email_tools as et
        self.orig_dir = et.DRAFTS_DIR
        et.DRAFTS_DIR = tempfile.mkdtemp()

    def tearDown(self):
        import tools.email_tools as et
        et.DRAFTS_DIR = self.orig_dir

    def test_draft_email(self):
        result = draft_email("test@example.com", "Hello", "Body here")
        self.assertIn("Draft email saved", result)
        drafts = list_drafts()
        self.assertIn(".eml", drafts)


class TestSystemTools(unittest.TestCase):
    def test_get_brightness_returns_string(self):
        result = get_brightness()
        self.assertIsInstance(result, str)

    def test_get_volume_returns_string(self):
        result = get_volume()
        self.assertIsInstance(result, str)

    def test_shutdown_schedules(self):
        result = shutdown_pc(delay_minutes=5)
        self.assertIn("Shutdown scheduled", result)

    def test_restart_schedules(self):
        result = restart_pc(delay_minutes=5)
        self.assertIn("Restart scheduled", result)

    def test_cancel_shutdown(self):
        result = cancel_shutdown()
        self.assertIn("cancelled", result.lower())


class TestMonitorTools(unittest.TestCase):
    def test_get_cpu_usage(self):
        result = get_cpu_usage()
        self.assertIsInstance(result, str)

    def test_get_memory_usage(self):
        result = get_memory_usage()
        self.assertIsInstance(result, str)

    def test_get_disk_usage(self):
        result = get_disk_usage("/")
        self.assertIsInstance(result, str)

    def test_get_battery_status(self):
        result = get_battery_status()
        self.assertIsInstance(result, str)

    def test_get_full_pc_state(self):
        result = get_full_pc_state()
        self.assertIsInstance(result, str)
        if "error" not in result.lower():
            self.assertIn("CPU", result)


class TestEditTools(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, "test.txt")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read(self):
        write_result = write_file(self.test_file, "hello world")
        self.assertIn("Wrote", write_result)
        read_result = read_file(self.test_file)
        self.assertEqual(read_result, "hello world")

    def test_append(self):
        write_file(self.test_file, "line1\n")
        append_result = append_file(self.test_file, "line2\n")
        self.assertIn("Appended", append_result)
        content = read_file(self.test_file)
        self.assertIn("line1", content)
        self.assertIn("line2", content)

    def test_edit_line(self):
        write_file(self.test_file, "line1\nline2\nline3\n")
        edit_result = edit_file_line(self.test_file, 2, "new line 2")
        self.assertIn("Updated line 2", edit_result)
        content = read_file(self.test_file)
        self.assertIn("new line 2", content)


class TestResearchTools(unittest.TestCase):
    def setUp(self):
        import tools.research_tools as rt
        self.orig_dir = rt.REPORTS_DIR
        rt.REPORTS_DIR = tempfile.mkdtemp()

    def tearDown(self):
        import tools.research_tools as rt
        rt.REPORTS_DIR = self.orig_dir

    def test_list_reports_empty(self):
        result = list_reports()
        self.assertIn("No research reports", result)


class TestConsent(unittest.TestCase):
    def test_consent_copy_keys(self):
        required = ["install_time", "feature_time", "autonomy_opt_in", "module_install",
                    "knowledge_skill", "sensitive_action", "high_risk", "webcam", "email_send"]
        for key in required:
            self.assertIn(key, CONSENT_COPY)

    def test_consent_copy_not_empty(self):
        for key, text in CONSENT_COPY.items():
            self.assertTrue(len(text) > 0, f"Consent copy for {key} is empty")


if __name__ == "__main__":
    unittest.main()
