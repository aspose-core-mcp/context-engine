"""Tests for the mutmut 3.x baseline wrapper's parse + report path.

The wrapper was migrated from the removed mutmut 2.x
``results --output=json`` interface to 3.x ``export-cicd-stats`` (which
writes ``mutants/mutmut-cicd-stats.json``). These tests pin the parsing
and report-writing halves against the 3.x flat schema — hermetically,
with no dependency on the optional ``mutation`` extra being installed,
so they run in the standard ``[dev]`` CI environment.

The expensive half (actually running ``mutmut run`` over the sandbox)
is a scheduled CI-runner job and is intentionally not exercised here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path("scripts/checks/quality/run_mutation_baseline.py")


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_mutation_baseline", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclass field resolution looks the module up
    # in sys.modules via cls.__module__, which fails if it is absent.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


# ---------------------------------------------------------------------------
# _parse_results — the 3.x flat schema
# ---------------------------------------------------------------------------


def test_parse_results_computes_kill_rate_excluding_skipped_and_no_tests() -> None:
    stats = {
        "killed": 80,
        "survived": 20,
        "timeout": 0,
        "suspicious": 0,
        "skipped": 5,
        "no_tests": 10,
        "segfault": 0,
        "total": 115,
    }
    baseline = _MOD._parse_results(stats)
    # tested = killed + survived + timeout + suspicious = 100
    assert baseline.kill_rate == 0.8
    assert baseline.killed == 80
    assert baseline.survived == 20
    assert baseline.skipped == 5
    assert baseline.no_tests == 10
    assert baseline.total_mutants == 115


def test_parse_results_counts_timeout_as_caught() -> None:
    stats = {"killed": 70, "survived": 10, "timeout": 20, "suspicious": 0}
    baseline = _MOD._parse_results(stats)
    # (killed + timeout) / (killed + survived + timeout + suspicious)
    assert baseline.kill_rate == round(90 / 100, 4)
    assert baseline.timed_out == 20


def test_parse_results_empty_stats_is_zero_not_crash() -> None:
    baseline = _MOD._parse_results({})
    assert baseline.kill_rate == 0.0
    assert baseline.total_mutants == 0
    assert baseline.killed == 0


def test_parse_results_all_no_tests_yields_zero_kill_rate() -> None:
    # No mutant had a covering test → denominator is zero → 0.0, no div error.
    stats = {"killed": 0, "survived": 0, "no_tests": 12, "total": 12}
    baseline = _MOD._parse_results(stats)
    assert baseline.kill_rate == 0.0
    assert baseline.no_tests == 12


# ---------------------------------------------------------------------------
# _read_cicd_stats — file IO
# ---------------------------------------------------------------------------


def test_read_cicd_stats_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _MOD._read_cicd_stats(tmp_path / "nope.json") == {}


def test_read_cicd_stats_blank_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    path.write_text("   \n", encoding="utf-8")
    assert _MOD._read_cicd_stats(path) == {}


def test_read_cicd_stats_reads_flat_schema(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    path.write_text(
        json.dumps({"killed": 3, "survived": 1, "total": 4}), encoding="utf-8"
    )
    assert _MOD._read_cicd_stats(path) == {
        "killed": 3,
        "survived": 1,
        "total": 4,
    }


# ---------------------------------------------------------------------------
# _write_reports — end-to-end parse → write, hermetic via monkeypatched paths
# ---------------------------------------------------------------------------


def test_write_reports_emits_json_and_txt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    json_path = tmp_path / "reports" / "mutation-baseline.json"
    txt_path = tmp_path / "reports" / "mutation-baseline.txt"
    monkeypatch.setattr(_MOD, "REPORT_JSON", json_path)
    monkeypatch.setattr(_MOD, "REPORT_TXT", txt_path)

    baseline = _MOD._parse_results(
        {"killed": 9, "survived": 1, "total": 10}
    )
    _MOD._write_reports(baseline)

    assert json_path.exists()
    assert txt_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["killed"] == 9
    assert payload["survived"] == 1
    assert payload["kill_rate"] == 0.9
    assert "Kill rate:        0.9000" in txt_path.read_text(encoding="utf-8")
