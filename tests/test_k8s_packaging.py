from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_verify_helm_packaging_script_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "scripts/checks/k8s/verify_helm_packaging.py"]
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    output = f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    assert completed.returncode == 0, output
