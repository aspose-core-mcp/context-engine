"""Tests for the production structured-log sample provider.

Two layers:

1. **Unit** — the provider's parsing/mapping/tail/env contract over
   handcrafted JSONL (missing file, malformed lines, field aliases,
   minimum-field drop, tail limiting, env factory).
2. **Integration** — feed a fixture log into a real Coordinator and
   assert the samples flow through all seven agents
   (correlate → judge → llm-judge → diagnose → propose → guard → adapt)
   down to the CycleSummary.
"""

from __future__ import annotations

import json
from pathlib import Path

from adcs.quality_loop import (
    Coordinator,
    CoordinatorConfig,
    DiagnosisAgent,
    GuardAgent,
    JudgeAgent,
    LLMJudgeAgent,
    ProposalAgent,
    QueryResponseSample,
)
from adcs.quality_loop.sample_providers import (
    LOG_TAIL_ENV_VAR,
    StructuredLogSampleProvider,
)


def _write_log(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Unit: parsing, mapping, robustness
# ---------------------------------------------------------------------------


def test_missing_file_yields_empty_batch(tmp_path: Path) -> None:
    provider = StructuredLogSampleProvider(log_path=tmp_path / "absent.jsonl")
    assert provider() == ()


def test_maps_full_record_to_sample(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    _write_log(
        log,
        [
            {
                "query": "how to OCR a PDF in C#",
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "requested_version": "25.1",
                "strict_version": True,
                "candidates": [
                    {
                        "canonical_url": "https://docs.aspose.com/ocr/net/",
                        "version": "25.1",
                        "chunk_id": "c1",
                        "symbol_fqn": "Aspose.OCR.Recognize",
                    }
                ],
                "confidence_score": 0.85,
                "prompt_pack_version": "v-stable",
            }
        ],
    )
    (sample,) = StructuredLogSampleProvider(log_path=log)()
    assert isinstance(sample, QueryResponseSample)
    assert sample.product_id == "aspose.ocr"
    assert sample.programming_language == "net"
    assert sample.requested_version == "25.1"
    assert sample.strict_version is True
    assert sample.query == "how to OCR a PDF in C#"
    assert len(sample.candidates) == 1
    assert sample.confidence_score == 0.85
    assert sample.prompt_pack_version == "v-stable"
    assert sample.sample_id  # auto-generated when absent


def test_field_aliases_raw_query_version_confidence(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    _write_log(
        log,
        [
            {
                "raw_query": "ocr image to text",
                "product_id": "aspose.ocr",
                "programming_language": "java",
                "version": "24.5",
                "confidence": 0.7,
            }
        ],
    )
    (sample,) = StructuredLogSampleProvider(log_path=log)()
    assert sample.query == "ocr image to text"
    assert sample.requested_version == "24.5"
    assert sample.confidence_score == 0.7
    # Defaults for omitted fields.
    assert sample.strict_version is False
    assert sample.candidates == ()


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        fh.write("not json\n")
        fh.write("\n")
        fh.write(
            json.dumps(
                {
                    "query": "q",
                    "product_id": "aspose.ocr",
                    "programming_language": "net",
                }
            )
            + "\n"
        )
        fh.write("[1,2,3]\n")  # valid json, not a dict
    samples = StructuredLogSampleProvider(log_path=log)()
    assert len(samples) == 1


def test_records_missing_minimum_fields_are_dropped(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    _write_log(
        log,
        [
            {"product_id": "aspose.ocr", "programming_language": "net"},  # no query
            {"query": "q", "programming_language": "net"},  # no product_id
            {"query": "q", "product_id": "aspose.ocr"},  # no language
            {"query": "  ", "product_id": "aspose.ocr", "programming_language": "net"},
            {
                "query": "valid",
                "product_id": "aspose.ocr",
                "programming_language": "net",
            },
        ],
    )
    samples = StructuredLogSampleProvider(log_path=log)()
    assert len(samples) == 1
    assert samples[0].query == "valid"


def test_tail_keeps_only_most_recent_max_samples(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    _write_log(
        log,
        [
            {
                "query": f"q{i}",
                "product_id": "aspose.ocr",
                "programming_language": "net",
            }
            for i in range(10)
        ],
    )
    samples = StructuredLogSampleProvider(log_path=log, max_samples=3)()
    assert len(samples) == 3
    # Newest-last: the final three records survive.
    assert [s.query for s in samples] == ["q7", "q8", "q9"]


def test_confidence_bool_is_not_coerced(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    _write_log(
        log,
        [
            {
                "query": "q",
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "confidence_score": True,
            }
        ],
    )
    (sample,) = StructuredLogSampleProvider(log_path=log)()
    assert sample.confidence_score is None


# ---------------------------------------------------------------------------
# from_env factory
# ---------------------------------------------------------------------------


def test_from_env_returns_none_when_unset() -> None:
    assert StructuredLogSampleProvider.from_env(env={}) is None
    assert StructuredLogSampleProvider.from_env(env={LOG_TAIL_ENV_VAR: "  "}) is None


def test_from_env_builds_provider_when_set(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    _write_log(
        log,
        [{"query": "q", "product_id": "aspose.ocr", "programming_language": "net"}],
    )
    provider = StructuredLogSampleProvider.from_env(
        env={LOG_TAIL_ENV_VAR: str(log)}
    )
    assert provider is not None
    assert len(provider()) == 1


# ---------------------------------------------------------------------------
# Integration: samples flow through all seven agents to CycleSummary
# ---------------------------------------------------------------------------


class _MirrorJudgeClient:
    def judge(self, *, sample: QueryResponseSample):
        return 0.4, {}, "mirror-stub"


def _fixture_records() -> list[dict]:
    # A scope-clustered low-score batch so DiagnosisAgent finds a pattern
    # and ProposalAgent + GuardAgent have something to act on.
    records: list[dict] = []
    for i in range(6):
        records.append(
            {
                "query": f"ocr question {i}",
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "requested_version": "25.1",
                "strict_version": True,
                # No canonical_url → low citation accuracy → low score cluster.
                "candidates": [{"version": "25.1", "chunk_id": f"chunk-{i}"}],
                "confidence_score": 0.95,
            }
        )
    return records


def test_provider_feeds_real_coordinator_through_all_seven_agents(
    tmp_path: Path,
) -> None:
    log = tmp_path / "query-log.jsonl"
    _write_log(log, _fixture_records())

    config = CoordinatorConfig(
        audit_log_path=tmp_path / "audit.jsonl",
        summary_path=tmp_path / "summary.json",
        calibration_state_path=tmp_path / "calibration.json",
    )
    coord = Coordinator(
        config=config,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=StructuredLogSampleProvider(log_path=log),
        llm_judge=LLMJudgeAgent(client=_MirrorJudgeClient()),
    )

    summary = coord.run_cycle()

    # 1. Sample provider → samples; 2. JudgeAgent → verdicts.
    assert summary.samples_processed == 6
    assert summary.verdicts_emitted == 6
    # 3. CrossCycleCorrelationAgent (default-on) → 1 report.
    assert summary.correlation_reports_emitted == 1
    # 4. LLMJudgeAgent (wired) → 1 agreement report.
    assert summary.llm_judge_reports_emitted == 1
    # 5. DiagnosisAgent → at least one diagnosis (scope cluster present).
    assert summary.diagnoses_emitted >= 1
    # 6. ProposalAgent → at least one proposal.
    assert summary.proposals_emitted >= 1
    # 7. GuardAgent → one decision per proposal.
    assert summary.decisions_emitted == summary.proposals_emitted
    # AdaptiveAgent ran (calibration_state_path set) → state persisted.
    assert config.calibration_state_path.exists()
    # The audit log captured the full cycle.
    assert config.audit_log_path.exists()
