"""Acceptance and performance gate helpers for deterministic local checks."""

from adcs.quality_gates.eval_inputs import (
    GeneratedEvalInputs,
    build_eval_inputs,
    corpus_to_payload,
    dataset_to_payload,
    default_staging_manifest_paths,
    load_stage_d_corpus_from_artifact,
    load_stage_d_corpus_from_staging_manifests,
    summary_to_payload,
)
from adcs.quality_gates.go_no_go import (
    build_go_no_go_summary,
    render_go_no_go_human_report,
)
from adcs.quality_gates.golden_eval import (
    GoldenDataset,
    GoldenDatasetCase,
    load_golden_dataset,
    load_stage_d_corpus,
    render_golden_eval_human_report,
    run_golden_dataset_evaluation,
)
from adcs.quality_gates.perf_profiles import (
    PerfProfile,
    load_perf_profiles,
    render_perf_human_report,
    run_perf_profiles,
)
from adcs.quality_gates.release_readiness import (
    build_release_readiness_summary,
    render_release_readiness_human_report,
)

__all__ = [
    "GeneratedEvalInputs",
    "GoldenDataset",
    "GoldenDatasetCase",
    "PerfProfile",
    "build_eval_inputs",
    "build_go_no_go_summary",
    "build_release_readiness_summary",
    "corpus_to_payload",
    "dataset_to_payload",
    "default_staging_manifest_paths",
    "load_golden_dataset",
    "load_perf_profiles",
    "load_stage_d_corpus",
    "load_stage_d_corpus_from_artifact",
    "load_stage_d_corpus_from_staging_manifests",
    "render_golden_eval_human_report",
    "render_go_no_go_human_report",
    "render_perf_human_report",
    "render_release_readiness_human_report",
    "run_golden_dataset_evaluation",
    "run_perf_profiles",
    "summary_to_payload",
]
