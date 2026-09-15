"""Alert-firing semantics test via Prometheus `promtool test rules`.

The companion structural test (``test_alert_rules.py``) checks the
shape of the alert YAML. This test goes further — it replays synthetic
metric series through Prometheus's own rule evaluator and asserts that
each named alert *actually fires* under the breach conditions it
targets. The fixture lives at
``tests/observability/fixtures/alerts-firing-test.yaml`` and is the
canonical promtool `test rules` format.

The test is skipped when ``promtool`` is not on ``PATH``. To run it
locally, install promtool via
``brew install prometheus`` or by downloading the Prometheus release
archive.

The structural test proves the rules are well formed; this test proves
they fire.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "alerts-firing-test.yaml"
)


@pytest.mark.skipif(
    shutil.which("promtool") is None,
    reason="promtool not on PATH; install via `brew install prometheus` or the"
    " Prometheus release archive to enable alert-firing verification",
)
def test_alert_rules_fire_under_breach_conditions() -> None:
    """Replay the promtool fixture and assert all named alerts fire."""
    assert FIXTURE.exists(), f"missing alert firing fixture at {FIXTURE}"
    result = subprocess.run(
        ["promtool", "test", "rules", str(FIXTURE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"promtool test rules failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.skipif(
    shutil.which("promtool") is None, reason="promtool not on PATH"
)
def test_alert_rules_file_parses_via_promtool() -> None:
    """promtool's own structural validation must accept the rules file."""
    rules_path = (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "observability"
        / "prometheus"
        / "adcs-alerts.yaml"
    )
    result = subprocess.run(
        ["promtool", "check", "rules", str(rules_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"promtool check rules failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
