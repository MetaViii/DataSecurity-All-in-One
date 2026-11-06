"""Replay standalone exp.py files against already-verified complete contest outputs."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datasecurity.builtin import create_registry
from datasecurity.core.pipeline import Pipeline
from datasecurity.exporter import export_python

CASES = {
    "analysis": "ctf_real_analysis.json",
    "cleaning": "ctf_real_cleaning.json",
    "log": "ctf_real_log.json",
    "ycb24_analysis": "ctf_real_ycb24_analysis.json",
    "ycb24_traffic": "ctf_real_ycb24_traffic.json",
    "zj24_classify1": "ctf_real_zj24_classify1.json",
    "zj24_classify2": "ctf_real_zj24_classify2.json",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=CASES)
    args = parser.parse_args()
    registry = create_registry()
    root = ROOT / "work/python-export"
    root.mkdir(parents=True, exist_ok=True)
    report = {}
    for case in args.case or CASES:
        definition = json.loads((ROOT / "examples" / CASES[case]).read_text(encoding="utf-8"))
        exported = export_python(definition, registry)
        directory = root / case
        directory.mkdir(parents=True, exist_ok=True)
        script = directory / "exp.py"
        script.write_text(exported.script, encoding="utf-8", newline="\n")
        # -I excludes cwd/PYTHONPATH; -S also excludes installed packages when
        # no third-party library is needed. TShark is an external executable.
        command = [
            sys.executable,
            "-I",
            *([] if exported.requirements else ["-S"]),
            str(script),
            "--base-dir",
            str(ROOT / "examples"),
            "--output-dir",
            str(directory / "output"),
            "--overwrite",
            "--json",
        ]
        result = subprocess.run(
            command, cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=180
        )
        if result.returncode:
            raise RuntimeError(f"{case}: {result.stderr}")
        summary = json.loads(result.stdout)
        checks = {}
        for step in Pipeline(registry).plan(definition):
            if step.id not in exported.outputs:
                continue
            expected = (ROOT / "examples" / step.config["path"]).resolve()
            if not expected.is_file():
                raise FileNotFoundError(f"缺少基准结果 {expected}，请先运行原题复现脚本")
            actual = directory / "output" / exported.outputs[step.id]
            original, replay = expected.read_bytes(), actual.read_bytes()
            if replay != original:
                raise AssertionError(f"{case}/{actual.name} 与原流程不一致")
            checks[actual.name] = {
                "bytes": len(replay),
                "matches_original": True,
                "sha256": hashlib.sha256(replay).hexdigest(),
            }
        report[case] = {
            "status": "success",
            "script_bytes": len(exported.script.encode("utf-8")),
            "isolated_without_site_packages": not exported.requirements,
            "nodes": exported.nodes,
            "steps": summary["steps"],
            "files": checks,
        }
        print(f"{case}: {exported.nodes} steps, {len(checks)} files match", flush=True)
    path = root / "verification.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Verification: {path}")


if __name__ == "__main__":
    main()
