from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_run_release_go_no_go_script_passes_for_green_inputs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]

    evaluation = tmp_path / "evaluation.json"
    perf = tmp_path / "perf.json"
    readiness = tmp_path / "readiness.json"
    dr = tmp_path / "dr.json"
    helm = tmp_path / "helm.json"
    output_json = tmp_path / "go-no-go.json"
    output_log = tmp_path / "go-no-go.log"

    evaluation.write_text(json.dumps({"blocking_status": "pass"}), encoding="utf-8")
    perf.write_text(json.dumps({"blocking_status": "pass"}), encoding="utf-8")
    readiness.write_text(
        json.dumps({"blocking_status": "pass", "readiness_status": "ready"}),
        encoding="utf-8",
    )
    dr.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    helm.write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    command = [
        sys.executable,
        "scripts/checks/quality/run_release_go_no_go.py",
        "--phase",
        "preprod",
        "--evaluation",
        str(evaluation),
        "--perf",
        str(perf),
        "--release-readiness",
        str(readiness),
        "--dr-smoke",
        str(dr),
        "--helm-packaging",
        str(helm),
        "--output-json",
        str(output_json),
        "--output-log",
        str(output_log),
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    output = f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    assert completed.returncode == 0, output
    assert output_json.exists()
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["decision"] == "go"
