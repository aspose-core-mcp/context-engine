from __future__ import annotations

from adcs.ingestion.chunking import StageDChunkRecord
from adcs.quality_gates import (
    GoldenDataset,
    GoldenDatasetCase,
    PerfProfile,
    build_release_readiness_summary,
    run_golden_dataset_evaluation,
    run_perf_profiles,
)


def test_golden_dataset_evaluation_tracks_metrics_without_blockers() -> None:
    dataset = GoldenDataset(
        dataset_id="unit-golden",
        seed="unit-seed",
        cases=(
            GoldenDatasetCase(
                case_id="case-1",
                query="RecognizeImage 25.1",
                product_id="aspose.ocr",
                language="net",
                version="25.1",
                query_locale="en",
                strict_version=True,
                top_k=3,
                doc_types=("api_reference",),
                include_examples=True,
                expected_canonical_urls=(
                    "https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
                ),
                expected_version="25.1",
                scenario="symbol_exact",
            ),
        ),
    )
    summary = run_golden_dataset_evaluation(
        dataset=dataset,
        corpus=(
            _record(
                chunk_id="chunk-25-1",
                version="25.1",
                canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
            ),
        ),
    )

    assert summary["blocking_status"] == "pass"
    assert summary["metrics"]["top_3_relevance"] >= 1.0
    assert summary["metrics"]["version_accuracy"] >= 1.0
    assert summary["metrics"]["citation_coverage"] >= 1.0
    assert summary["breakdown"]["scenarios"]["symbol_exact"]["cases_total"] == 1
    assert summary["breakdown"]["scenarios"]["symbol_exact"]["regressions"] == 0
    assert "aspose.ocr" in summary["breakdown"]["products"]
    assert summary["breakdown"]["products"]["aspose.ocr"]["cases_total"] == 1
    assert summary["breakdown"]["products"]["aspose.ocr"]["top_3_hits"] == 1
    assert summary["breakdown"]["products"]["aspose.ocr"]["top_3_relevance"] == 1.0


def test_golden_dataset_evaluation_blocks_on_functional_regression() -> None:
    dataset = GoldenDataset(
        dataset_id="unit-golden-fail",
        seed="unit-seed",
        cases=(
            GoldenDatasetCase(
                case_id="case-2",
                query="RecognizeImage 24.12",
                product_id="aspose.ocr",
                language="net",
                version="24.12",
                query_locale="en",
                strict_version=True,
                top_k=3,
                doc_types=("api_reference",),
                include_examples=True,
                expected_canonical_urls=(
                    "https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/24-12/",
                ),
                expected_version="24.12",
            ),
        ),
    )
    summary = run_golden_dataset_evaluation(
        dataset=dataset,
        corpus=(
            _record(
                chunk_id="chunk-25-1",
                version="25.1",
                canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
            ),
        ),
    )

    assert summary["blocking_status"] == "fail"
    assert summary["functional_regressions"]


def test_golden_dataset_preprod_blocks_on_target_miss() -> None:
    dataset = GoldenDataset(
        dataset_id="unit-golden-preprod",
        seed="unit-seed",
        cases=(
            GoldenDatasetCase(
                case_id="case-preprod-1",
                query="RecognizeImage 25.1",
                product_id="aspose.ocr",
                language="net",
                version="25.1",
                query_locale="en",
                strict_version=False,
                top_k=3,
                doc_types=("api_reference",),
                include_examples=True,
                expected_canonical_urls=(
                    "https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
                ),
                expected_version=None,
            ),
        ),
    )
    summary = run_golden_dataset_evaluation(
        dataset=dataset,
        corpus=(
            _record(
                chunk_id="chunk-other",
                version="25.1",
                canonical_url="https://reference.aspose.com/ocr/net/asposeocr/other/25-1/",
            ),
        ),
        phase="preprod",
    )

    assert summary["functional_regressions"] == []
    assert "top_3_relevance" in summary["target_misses"]
    assert summary["blocking_status"] == "fail"


def test_perf_profiles_use_defaults_and_keep_soak_optional() -> None:
    dataset = GoldenDataset(
        dataset_id="unit-perf",
        seed="unit-seed",
        cases=(
            GoldenDatasetCase(
                case_id="case-3",
                query="RecognizeImage",
                product_id="aspose.ocr",
                language="net",
                version="25.1",
                query_locale="en",
                strict_version=True,
                top_k=3,
                doc_types=("api_reference",),
                include_examples=True,
                expected_canonical_urls=(
                    "https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
                ),
                expected_version="25.1",
            ),
        ),
    )
    profiles = (
        PerfProfile(
            profile_id="sustained",
            target_rps=2,
            duration_seconds=1,
            run_by_default=True,
            description="unit sustained",
        ),
        PerfProfile(
            profile_id="soak",
            target_rps=2,
            duration_seconds=1,
            run_by_default=False,
            description="unit soak",
        ),
    )
    summary = run_perf_profiles(
        dataset=dataset,
        corpus=(
            _record(
                chunk_id="chunk-25-1",
                version="25.1",
                canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
            ),
        ),
        profiles=profiles,
        selected_profile_ids=None,
    )

    profile_by_id = {
        profile["profile_id"]: profile
        for profile in summary["profiles"]
    }
    assert profile_by_id["sustained"]["executed"] is True
    assert profile_by_id["soak"]["executed"] is False


def test_perf_profiles_preprod_blocks_on_target_miss_without_regressions() -> None:
    dataset = GoldenDataset(
        dataset_id="unit-perf-preprod",
        seed="unit-seed",
        cases=(
            GoldenDatasetCase(
                case_id="case-perf-preprod",
                query="RecognizeImage",
                product_id="aspose.ocr",
                language="net",
                version="25.1",
                query_locale="en",
                strict_version=False,
                top_k=3,
                doc_types=("api_reference",),
                include_examples=True,
                expected_canonical_urls=(
                    "https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
                ),
                expected_version=None,
            ),
        ),
    )
    profiles = (
        PerfProfile(
            profile_id="sustained",
            target_rps=20000,
            duration_seconds=1,
            run_by_default=True,
            description="unit sustained preprod hard gate",
        ),
    )
    summary = run_perf_profiles(
        dataset=dataset,
        corpus=(
            _record(
                chunk_id="chunk-25-1",
                version="25.1",
                canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
            ),
        ),
        profiles=profiles,
        selected_profile_ids=None,
        phase="preprod",
    )

    assert summary["functional_regressions"] == []
    assert any(item.startswith("sustained:throughput_rps") for item in summary["target_misses"])
    assert summary["blocking_status"] == "fail"


def test_perf_profiles_preprod_confirms_multi_product_capacity_envelope() -> None:
    dataset = GoldenDataset(
        dataset_id="unit-perf-capacity",
        seed="unit-seed",
        cases=(
            GoldenDatasetCase(
                case_id="case-perf-capacity",
                query="RecognizeImage",
                product_id="aspose.ocr",
                language="net",
                version="25.1",
                query_locale="en",
                strict_version=False,
                top_k=3,
                doc_types=("api_reference",),
                include_examples=True,
                expected_canonical_urls=(
                    "https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
                ),
                expected_version=None,
            ),
        ),
    )
    profiles = (
        PerfProfile(
            profile_id="capacity-100-products",
            target_rps=4,
            duration_seconds=1,
            run_by_default=True,
            description="unit capacity profile",
            simulated_products=120,
            required_min_products=100,
        ),
    )
    summary = run_perf_profiles(
        dataset=dataset,
        corpus=(
            _record(
                chunk_id="chunk-25-1",
                version="25.1",
                canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
            ),
        ),
        profiles=profiles,
        selected_profile_ids=None,
        phase="preprod",
    )

    assert summary["blocking_status"] == "pass"
    assert summary["capacity"]["max_unique_products_corpus"] >= 100
    assert not any(
        item.startswith("capacity-100-products:simulated_product_count")
        for item in summary["target_misses"]
    )


def test_perf_profiles_preprod_blocks_when_capacity_target_is_not_met() -> None:
    dataset = GoldenDataset(
        dataset_id="unit-perf-capacity-miss",
        seed="unit-seed",
        cases=(
            GoldenDatasetCase(
                case_id="case-perf-capacity-miss",
                query="RecognizeImage",
                product_id="aspose.ocr",
                language="net",
                version="25.1",
                query_locale="en",
                strict_version=False,
                top_k=3,
                doc_types=("api_reference",),
                include_examples=True,
                expected_canonical_urls=(
                    "https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
                ),
                expected_version=None,
            ),
        ),
    )
    profiles = (
        PerfProfile(
            profile_id="capacity-too-small",
            target_rps=3,
            duration_seconds=1,
            run_by_default=True,
            description="unit capacity miss profile",
            simulated_products=40,
            required_min_products=100,
        ),
    )
    summary = run_perf_profiles(
        dataset=dataset,
        corpus=(
            _record(
                chunk_id="chunk-25-1",
                version="25.1",
                canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/25-1/",
            ),
        ),
        profiles=profiles,
        selected_profile_ids=None,
        phase="preprod",
    )

    assert summary["blocking_status"] == "fail"
    assert any(
        item.startswith("capacity-too-small:simulated_product_count")
        for item in summary["target_misses"]
    )


def test_release_readiness_keeps_target_misses_non_blocking_in_mvp() -> None:
    summary = build_release_readiness_summary(
        evaluation_summary={
            "blocking_status": "pass",
            "counts": {"cases_total": 4},
            "target_misses": ("top_3_relevance",),
        },
        perf_summary={
            "blocking_status": "pass",
            "target_misses": ("sustained:throughput_rps",),
            "profiles": [
                {"profile_id": "sustained", "executed": True},
                {"profile_id": "burst", "executed": True},
                {"profile_id": "soak", "executed": False}
            ],
        },
    )

    assert summary["blocking_status"] == "pass"
    assert summary["readiness_status"] == "ready_for_mvp_tracking"
    assert "top_3_relevance" in summary["target_misses"]
    assert "sustained:throughput_rps" in summary["target_misses"]


def test_release_readiness_preprod_blocks_on_target_miss() -> None:
    summary = build_release_readiness_summary(
        evaluation_summary={
            "blocking_status": "pass",
            "counts": {"cases_total": 4},
            "target_misses": ("top_3_relevance",),
        },
        perf_summary={
            "blocking_status": "pass",
            "target_misses": (),
            "profiles": [
                {"profile_id": "sustained", "executed": True},
                {"profile_id": "burst", "executed": True},
            ],
        },
        phase="preprod",
    )

    assert summary["blocking_status"] == "fail"
    assert summary["readiness_status"] == "blocked"
    assert summary["policy"]["target_enforcement"] == "hard_block"


def _record(
    *,
    chunk_id: str,
    version: str,
    canonical_url: str,
    product_id: str = "aspose.ocr",
) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id="aspose.ocr.apiref",
        product_id=product_id,
        product_family="Aspose.OCR",
        programming_language="net",
        version=version,
        source_kind="apiref",
        doc_locale="en",
        doc_type="api_signature",
        symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
        title="RecognizeImage Method",
        section_path=("root", "RecognizeImage"),
        canonical_url=canonical_url,
        section_anchor="#recognizeimage",
        source_path=f"source/{chunk_id}.md",
        source_revision=f"revision-{version}",
        is_deprecated=False,
        has_code_example=False,
        chunk_type="api_signature",
        text="public RecognitionResult RecognizeImage(string imagePath)",
        tokens=7,
        checksum=f"checksum-{chunk_id}",
    )
