"""Verify Web template paths, formal execution and downloaded original-contest CSV bytes.

Run contest_round2.py first. Uses FastAPI TestClient locally, never a live contest checker.
"""

import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from datasecurity.web.app import create_app


def wait(client, id):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] not in {"queued", "running"}:
            if job["status"] != "success":
                raise RuntimeError(job)
            return job
        time.sleep(0.03)
    raise TimeoutError("Web task did not finish")


def main():
    cases = {
        "ycb24_analysis": 10000,
        "ycb24_traffic": 294,
        "zj24_classify1": 20000,
        "zj24_classify2": 4221,
    }
    report = {}
    with TestClient(create_app(ROOT)) as client:
        bootstrap = client.get("/api/bootstrap").json()
        headers = {"X-Workspace-Token": bootstrap["token"]}
        templates = {item["id"]: item for item in bootstrap["templates"]}
        for case, rows in cases.items():
            expected = ROOT / f"work/contest-round2/results/{case}/submission.csv"
            if not expected.exists():
                raise FileNotFoundError("Run python scripts/contest_round2.py first")
            template = templates["ctf_real_" + case]
            response = client.post(
                "/api/runs",
                json={"definition": template["definition"], "preview": False},
                headers=headers,
            )
            response.raise_for_status()
            job = wait(client, response.json()["id"])
            artifact = next(item for item in job["artifacts"] if item["name"] == "submission.csv")
            download = client.get(artifact["url"])
            download.raise_for_status()
            if download.content != expected.read_bytes():
                raise AssertionError(f"{case}: Web CSV differs from CLI CSV")
            actual_rows = (
                len(list(csv.reader(io.StringIO(download.content.decode("utf-8-sig"))))) - 1
            )
            if actual_rows != rows:
                raise AssertionError((case, actual_rows, rows))
            report[case] = {
                "status": job["status"],
                "job_id": job["id"],
                "submission_rows": actual_rows,
                "matches_cli_bytes": True,
                "sha256": hashlib.sha256(download.content).hexdigest(),
                "artifacts": job["artifacts"],
            }
            print(case, "Web download matches CLI:", actual_rows, "rows")
        response = client.post(
            "/api/runs",
            json={"definition": templates["ctf_correction"]["definition"], "preview": False},
            headers=headers,
        )
        response.raise_for_status()
        job = wait(client, response.json()["id"])
        summary = client.get(
            f"/api/runs/{job['id']}/table", params={"node": "score", "port": "summary"}
        ).json()["rows"][0]["values"]
        if summary["正确率"] != "1" or summary["达标"] != "是":
            raise AssertionError(summary)
        differences = client.get(
            f"/api/runs/{job['id']}/table.csv", params={"node": "before", "port": "differences"}
        )
        differences.raise_for_status()
        if len(list(csv.DictReader(io.StringIO(differences.text)))) != 5:
            raise AssertionError("difference download is incomplete")
        report["synthetic_correction"] = {
            "status": job["status"],
            "job_id": job["id"],
            "summary": summary,
            "artifacts": job["artifacts"],
            "before_difference_rows": 5,
        }
    output = ROOT / "work/contest-round2/web-verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Web verification saved:", output)


if __name__ == "__main__":
    main()
