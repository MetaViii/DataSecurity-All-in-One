import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from datasecurity import Plugin, PluginSpec
from datasecurity.web.app import create_app
from tests.test_framework import flow, node


class PluginManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.builtin_count = len(self.app.state.workspace.registry.describe())
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {"X-Workspace-Token": self.client.get("/api/bootstrap").json()["token"]}
        self.template = self.client.get("/api/plugins/manage").json()["templates"][0]

    def post(self, url, payload):
        return self.client.post(url, json=payload, headers=self.headers)

    def install(self, **changes):
        return self.post(
            "/api/plugins/install",
            {"filename": "mine.py", "source": self.template["source"], "trusted": True, **changes},
        )

    def test_install_disable_enable_restart_preserve_source_and_catalog(self):
        result = self.install()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("local.my_transform", [p["id"] for p in result.json()["plugins"]])
        disabled = self.post("/api/plugins/toggle", {"filename": "mine.py", "enabled": False})
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["files"][0]["enabled"])
        self.assertTrue((self.root / "plugins/mine.py.disabled").exists())
        self.assertNotIn("local.my_transform", [p["id"] for p in disabled.json()["plugins"]])
        self.assertEqual(
            self.post("/api/plugins/toggle", {"filename": "mine.py", "enabled": True}).status_code,
            422,
        )
        enabled = self.post(
            "/api/plugins/toggle", {"filename": "mine.py", "enabled": True, "trusted": True}
        )
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.app.state.workspace.reload_plugins()
        self.assertEqual(
            (self.root / "plugins/mine.py").read_text(encoding="utf-8"), self.template["source"]
        )
        self.assertEqual(
            self.app.state.workspace.registry.get("local.my_transform").spec.name, "我的字段处理"
        )

    def test_untrusted_syntax_duplicate_id_and_filename_never_replace_existing(self):
        self.assertEqual(self.install(trusted=False).status_code, 422)
        self.assertEqual(self.install(source="invalid python !").status_code, 422)
        self.assertEqual(self.install(filename="../escape.py").status_code, 422)
        self.assertEqual(self.install(filename="CON.py").status_code, 422)
        self.assertEqual(self.install().status_code, 200)
        self.assertEqual(self.install(source="# overwrite").status_code, 422)
        failed = self.install(filename="other.py")
        self.assertEqual(failed.status_code, 422)
        self.assertIn("重复", failed.json()["error"])
        self.assertFalse((self.root / "plugins/other.py").exists())
        self.assertEqual(len(self.app.state.workspace.registry.describe()), self.builtin_count + 1)

    def test_failed_plugin_keeps_registry_and_system_exit_is_reported(self):
        for source in ["raise RuntimeError('boom')", "raise SystemExit(1)", "PLUGINS=[]"]:
            self.assertEqual(self.install(source=source).status_code, 422)
        self.assertEqual(len(self.app.state.workspace.registry.describe()), self.builtin_count)
        self.assertFalse((self.root / "plugins/mine.py").exists())

    def test_reload_bypasses_same_size_same_timestamp_bytecode(self):
        self.assertEqual(self.install().status_code, 200)
        file = self.root / "plugins/mine.py"
        file.write_text(
            self.template["source"].replace("我的字段处理", "你的字段处理"), encoding="utf-8"
        )
        result = self.post("/api/plugins/reload", {})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            self.app.state.workspace.registry.get("local.my_transform").spec.name, "你的字段处理"
        )

    def test_active_job_blocks_install_and_reload_and_toggle(self):
        class Wait(Plugin):
            spec = PluginSpec("test.wait", "wait", "input", "test", outputs=("data",))

            def run(self, inputs, config, context):
                while True:
                    context.check_cancelled()
                    time.sleep(0.005)

        self.app.state.workspace.registry.register(Wait())
        job = self.post("/api/runs", {"definition": flow(node("wait", "test.wait"))}).json()
        self.assertEqual(self.install().status_code, 409)
        self.assertEqual(self.post("/api/plugins/reload", {}).status_code, 409)
        self.assertEqual(
            self.post("/api/plugins/toggle", {"filename": "mine.py", "enabled": False}).status_code,
            409,
        )
        self.post(f'/api/runs/{job["id"]}/cancel', {})

    def test_write_token_required_and_source_limit(self):
        self.assertEqual(self.client.post("/api/plugins/install", json={}).status_code, 403)
        self.assertEqual(self.install(source="#" * (256 * 1024 + 1)).status_code, 422)

    def test_plugin_template_can_process_data_via_web_run(self):
        self.assertEqual(self.install().status_code, 200)
        (self.root / "data.csv").write_text("id\n001\n002\n", encoding="utf-8")
        definition = flow(
            node("read", "csv.read", {"path": "data.csv"}),
            node(
                "custom", "local.my_transform", {"field": "id", "prefix": "CTF_"}, data="read:data"
            ),
        )
        job = self.post("/api/runs", {"definition": definition}).json()
        for _ in range(100):
            snapshot = self.client.get(f'/api/runs/{job["id"]}').json()
            if snapshot["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        self.assertEqual(snapshot["status"], "success", snapshot)
        rows = self.client.get(
            f'/api/runs/{job["id"]}/table', params={"node": "custom", "port": "data"}
        ).json()["rows"]
        self.assertEqual([r["values"]["id"] for r in rows], ["CTF_001", "CTF_002"])
