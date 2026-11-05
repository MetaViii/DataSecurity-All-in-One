import tempfile
import csv
import io
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from datasecurity.web.app import create_app
from datasecurity import Plugin, PluginSpec
from tests.test_framework import flow, node


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.client.__exit__, None, None, None)
        self.bootstrap = self.client.get("/api/bootstrap").json()
        self.headers = {"X-Workspace-Token": self.bootstrap["token"]}

    def post(self, path, payload):
        return self.client.post(path, json=payload, headers=self.headers)

    def upload(self, content=b"id,n\n0001,10\n0002,20\n", name="data.csv"):
        response = self.client.post(
            "/api/files", files={"file": (name, content)}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait(self, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/runs/{job_id}").json()
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(0.01)
        self.fail("job did not finish")

    def test_bootstrap_host_token_origin_and_malformed_payloads(self):
        self.assertTrue(
            {"csv.read", "columns.realign", "validate.signature", "text.records"}
            <= {p["id"] for p in self.bootstrap["plugins"]}
        )
        self.assertEqual(
            self.client.get("/api/health", headers={"host": "attacker.invalid"}).status_code, 400
        )
        self.assertEqual(self.client.post("/api/projects", json={}).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/projects",
                json={},
                headers={**self.headers, "origin": "https://attacker.invalid"},
            ).status_code,
            403,
        )
        for definition in (
            {"nodes": None},
            {"nodes": [{"plugin": "csv.read", "config": []}]},
            {"version": 1, "nodes": []},
        ):
            self.assertEqual(
                self.post("/api/validate", {"definition": definition}).status_code, 422
            )
        self.assertEqual(
            self.post("/api/projects", {"id": 123, "definition": flow()}).status_code, 422
        )
        self.assertEqual(self.client.get("/api/unknown").status_code, 404)

    def test_upload_metadata_invalid_excel_and_project_revision(self):
        file = self.upload(name="../../data.csv")
        self.assertTrue(file["path"].startswith("work/uploads/"))
        self.assertEqual(file["columns"], ["id", "n"])
        broken = self.upload(b"not an xlsx", "broken.xlsx")
        self.assertIn("note", broken)
        self.assertEqual(
            self.client.post(
                "/api/files", files={"file": ("a.exe", b"x")}, headers=self.headers
            ).status_code,
            415,
        )
        definition = flow(node("read", "csv.read", {"path": file["path"]}))
        saved = self.post("/api/projects", {"name": "test", "definition": definition}).json()
        update = {**saved, "name": "updated"}
        self.assertEqual(self.post("/api/projects", update).json()["revision"], 2)
        self.assertEqual(self.post("/api/projects", update).status_code, 422)
        self.assertEqual(self.client.get(f"/api/projects/{saved['id']}").json()["name"], "updated")
        self.assertEqual(
            self.client.delete(f"/api/projects/{saved['id']}", headers=self.headers).status_code,
            200,
        )

    def test_full_preview_paging_search_and_selected_node_scope(self):
        file = self.upload(("id,n\n" + "".join(f"{i:04},{i}\n" for i in range(1201))).encode())
        definition = flow(
            node("read", "csv.read", {"path": file["path"]}),
            node(
                "sort",
                "rows.sort",
                {"rules": [{"field": "n", "type": "number", "direction": "desc"}]},
                data="read:data",
            ),
            node("unfinished", "csv.read"),
        )
        response = self.post(
            "/api/runs", {"definition": definition, "preview": True, "target": "sort"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        job = self.wait(response.json()["id"])
        self.assertEqual(job["status"], "success", job)
        page = self.client.get(
            f"/api/runs/{job['id']}/table",
            params={"node": "sort", "port": "data", "page": 2, "page_size": 500},
        ).json()
        self.assertEqual((page["row_count"], len(page["rows"])), (1201, 500))
        self.assertEqual(page["rows"][0]["values"]["n"], "700")
        search = self.client.get(
            f"/api/runs/{job['id']}/table", params={"node": "sort", "port": "data", "q": "1200"}
        ).json()
        self.assertEqual(search["filtered_count"], 1)
        original = self.client.get(
            f"/api/runs/{job['id']}/table", params={"node": "sort", "port": "data", "view": "input"}
        ).json()
        self.assertEqual(original["rows"][0]["values"]["id"], "0000")
        self.assertEqual(job["artifacts"], [])
        self.assertEqual(
            self.post(
                "/api/runs", {"definition": definition, "preview": False, "target": "sort"}
            ).status_code,
            422,
        )

    def test_preview_no_export_and_per_run_download(self):
        file = self.upload()
        definition = flow(
            node("read", "csv.read", {"path": file["path"]}),
            node("save", "csv.write", {"path": "../../answer.csv"}, data="read:data"),
        )
        preview = self.wait(self.post("/api/runs", {"definition": definition}).json()["id"])
        self.assertEqual(preview["status"], "success")
        self.assertEqual(list((self.root / "work/exports").iterdir()), [])
        urls = []
        for _ in range(2):
            job = self.wait(
                self.post("/api/runs", {"definition": definition, "preview": False}).json()["id"]
            )
            self.assertEqual(job["status"], "success", job)
            self.assertEqual(len(job["artifacts"]), 1)
            url = job["artifacts"][0]["url"]
            urls.append(url)
            self.assertIn("0001", self.client.get(url).text)
        self.assertNotEqual(*urls)
        self.assertFalse((self.root / "answer.csv").exists())

    def test_branch_csv_download_contains_full_unfiltered_result_and_preserves_values(self):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["id", "value"])
        rows = [[str(i).zfill(5), '中文,\n"quoted"' if i == 0 else str(i)] for i in range(601)]
        writer.writerows(rows)
        file = self.upload(buffer.getvalue().encode("utf-8"))
        definition = flow(node("read", "csv.read", {"path": file["path"]}))
        job = self.wait(self.post("/api/runs", {"definition": definition}).json()["id"])
        response = self.client.get(
            f"/api/runs/{job['id']}/table.csv", params={"node": "read", "port": "data"}
        )
        self.assertEqual(response.status_code, 200)
        exported = list(csv.reader(io.StringIO(response.text)))
        self.assertEqual(exported[0], ["id", "value"])
        self.assertEqual(exported[1:], rows)
        self.assertEqual(job["artifacts"], [])
        self.assertEqual(
            self.client.get(
                f"/api/runs/{job['id']}/table.csv", params={"node": "unknown", "port": "data"}
            ).status_code,
            422,
        )

    def test_capture_upload_selects_http_reader_without_parsing_on_upload(self):
        file = self.upload(b"not yet parsed", "capture.pcapng")
        self.assertEqual(file["reader"], "pcap.http")
        self.assertIn("正文", file["columns"])

    def test_failure_preserves_completed_tables_and_rejects_outside_input(self):
        file = self.upload()
        definition = flow(
            node("read", "csv.read", {"path": file["path"]}),
            node("bad", "columns.select", {"fields": ["missing"]}, data="read:data"),
        )
        job = self.wait(self.post("/api/runs", {"definition": definition}).json()["id"])
        self.assertEqual((job["status"], job["error_node"]), ("error", "bad"))
        self.assertEqual(job["nodes"][0]["ports"]["data"]["rows"], 2)
        outside = flow(node("read", "csv.read", {"path": "../outside.csv"}))
        job = self.wait(self.post("/api/runs", {"definition": outside}).json()["id"])
        self.assertEqual(job["status"], "error")
        self.assertIn("工作区", job["error"])

    def test_running_task_can_be_cooperatively_cancelled(self):
        class WaitingInput(Plugin):
            spec = PluginSpec("test.wait", "等待取消", "input", "测试用", outputs=("data",))

            def run(self, inputs, config, context):
                while True:
                    context.check_cancelled()
                    time.sleep(0.005)

        self.app.state.workspace.registry.register(WaitingInput())
        response = self.post("/api/runs", {"definition": flow(node("wait", "test.wait"))})
        job_id = response.json()["id"]
        self.assertEqual(self.post(f"/api/runs/{job_id}/cancel", {}).status_code, 200)
        self.assertEqual(self.wait(job_id)["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
