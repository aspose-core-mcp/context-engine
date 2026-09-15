from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from adcs.api import admin_system
from adcs.api.main import create_app
from adcs.api.public_docs_query import (
    BreakingChangeCitationResponse,
    BreakingChangeItemResponse,
    ListBreakingChangesResponse,
    ListLatestReleaseFeaturesResponse,
    ReleaseFeatureCitationResponse,
    ReleaseFeatureItemResponse,
)
from adcs.config import clear_settings_cache
from adcs.indexing.index_models import SnapshotRecord, SnapshotStatus
from adcs.ingestion.chunking import StageDChunkRecord, StageDExecutableSnippet


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_public_status_returns_filtered_mcp_service_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_check_dependencies(
        *_: object,
        **__: object,
    ) -> admin_system.readiness.DependencyResults:
        return {
            "postgres": (True, "reachable"),
            "redis": (True, "reachable"),
            "qdrant": (True, "reachable"),
            "opensearch": (False, "warming_up"),
        }

    monkeypatch.setattr(admin_system.readiness, "check_dependencies", _fake_check_dependencies)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/status", params={"repo_id": "aspose.ocr.docs"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["filters"] == {"product_id": None, "repo_id": "aspose.ocr.docs"}
    assert payload["dependencies"]["postgres"]["status"] == "ready"
    assert payload["dependencies"]["opensearch"]["status"] == "not_ready"
    assert isinstance(payload["dependencies"]["opensearch"]["required"], bool)
    assert len(payload["dependencies"]["opensearch"]["fix_plan"]) >= 2
    assert payload["total_services"] == 1
    assert len(payload["services"]) == 1
    assert payload["services"][0]["repo_id"] == "aspose.ocr.docs"
    assert isinstance(payload["services"][0]["service_status_summary"], str)


def test_public_mcp_config_export_returns_ready_client_snippets() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/mcp-configs",
            params={"product_id": "aspose.ocr", "transport": "streamable-http"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["server_name"] == "aspose-ocr"
    assert payload["product_id"] == "aspose.ocr"
    assert payload["transport"] == "streamable-http"
    assert payload["mcp_url"].endswith("/mcp/v1/streamable-http")
    snippets_by_client = {item["client_id"]: item for item in payload["clients"]}
    assert set(snippets_by_client) == {"cursor", "claude-desktop", "qwen-code", "vscode"}
    assert ".cursor/mcp.json" == snippets_by_client["cursor"]["config_path_hint"]
    assert "\"url\": \"http://testserver/mcp/v1/streamable-http\"" in snippets_by_client["cursor"][
        "snippet"
    ]
    assert "\"type\": \"http\"" in snippets_by_client["claude-desktop"]["snippet"]
    assert "\"httpUrl\": \"http://testserver/mcp/v1/streamable-http\"" in snippets_by_client[
        "qwen-code"
    ]["snippet"]
    assert "\"servers\"" in snippets_by_client["vscode"]["snippet"]


def test_public_starter_packs_return_guided_onboarding_bundles() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/starter-packs",
            params={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "transport": "streamable-http",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "aspose.ocr"
    assert payload["programming_language"] == "net"
    assert len(payload["packs"]) == 4
    cursor_pack = next(item for item in payload["packs"] if item["client_id"] == "cursor")
    assert cursor_pack["config_path_hint"] == ".cursor/mcp.json"
    assert "Resolve product `aspose.ocr`" in cursor_pack["starter_prompt"]
    assert len(cursor_pack["first_queries"]) == 3
    assert cursor_pack["download_filename"].endswith("-starter-pack.md")


def test_public_coverage_gap_tracker_separates_registered_and_ready_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        return tuple(
            record
            for record in chunk_records
            if (product_id is None or record.product_id == product_id)
            and (
                programming_language is None
                or record.programming_language == programming_language
            )
            and (version is None or record.version == version)
        )

    docs_service = admin_system.AdminContentServiceHealthResponse(
        repo_id="aspose.words.docs",
        product_id="aspose.words",
        product_family="aspose",
        product_family_dir="Aspose.Words",
        source_kind="docs",
        git_url="https://example.invalid/aspose.words.docs.git",
        default_branch="master",
        submodule_path="source-repo-docs/Aspose.Words",
        layout_type="doc_locale/programming_language/content",
        layout_confidence=0.99,
        latest_operation_id="ing-op-1",
        latest_operation_status="completed",
        latest_operation_finished_at=datetime.now(tz=UTC),
        parse_warnings_count=0,
        failed_items_count=0,
        active_snapshot_id="snap-docs-net",
        active_snapshot_created_at=datetime.now(tz=UTC),
        active_scopes_count=1,
        supported_programming_languages=["net"],
        supported_versions=["25.3"],
        mcp_ready=True,
        onboarding_status="active",
        service_status="healthy",
        service_status_reason="active_snapshot_available",
        indicator_color="success",
        service_status_summary="Docs are ready.",
        fix_plan=["No action required."],
    )
    apiref_service = admin_system.AdminContentServiceHealthResponse(
        repo_id="aspose.words.apiref",
        product_id="aspose.words",
        product_family="aspose",
        product_family_dir="Aspose.Words",
        source_kind="apiref",
        git_url="https://example.invalid/aspose.words.apiref.git",
        default_branch="main",
        submodule_path="source-repo-apiref/Aspose.Words",
        layout_type="doc_locale/programming_language/namespace",
        layout_confidence=0.99,
        latest_operation_id="ing-op-2",
        latest_operation_status="completed",
        latest_operation_finished_at=datetime.now(tz=UTC),
        parse_warnings_count=0,
        failed_items_count=0,
        active_snapshot_id=None,
        active_snapshot_created_at=None,
        active_scopes_count=0,
        supported_programming_languages=[],
        supported_versions=[],
        mcp_ready=False,
        onboarding_status="ingested",
        service_status="warning",
        service_status_reason="completed_without_active_snapshot",
        indicator_color="warning",
        service_status_summary="API reference is registered but not published.",
        fix_plan=["Publish an active snapshot."],
    )
    snapshots = [
        SnapshotRecord(
            snapshot_id="snap-docs-net",
            product_id="aspose.words",
            programming_language="net",
            version="25.3",
            source_kind="docs",
            source_revision="rev-docs",
            status=SnapshotStatus.ACTIVE,
            indexed_chunks_count=12,
            created_at=datetime.now(tz=UTC),
        )
    ]
    chunk_records = (
        StageDChunkRecord(
            chunk_id="chunk-words-1",
            repo_id="aspose.words.docs",
            product_id="aspose.words",
            product_family="Aspose.Words",
            programming_language="net",
            version="25.3",
            source_kind="docs",
            doc_locale="en",
            doc_type="guide",
            symbol_fqn=None,
            title="Aspose.Words quickstart",
            section_path=("guide",),
            canonical_url="https://docs.aspose.com/words/net/quickstart/",
            section_anchor="#quickstart",
            source_path="en/net/getting-started/_index.md",
            source_revision="rev-docs",
            is_deprecated=False,
            has_code_example=True,
            chunk_type="guide_step",
            text="Use Aspose.Words in .NET.",
            tokens=110,
            checksum="words-checksum-1",
            executable_snippets=(
                StageDExecutableSnippet(
                    snippet_id="snippet-words-1",
                    language="csharp",
                    code="var doc = new Document();",
                    parent_canonical_url="https://docs.aspose.com/words/net/quickstart/",
                    parent_section_anchor="#quickstart",
                    parent_symbol_fqn=None,
                ),
            ),
        ),
    )

    monkeypatch.setattr(
        admin_system,
        "_collect_content_service_rows",
        lambda request, product_id=None, repo_id=None: [docs_service, apiref_service],
    )
    monkeypatch.setattr(
        admin_system,
        "_snapshot_registry",
        lambda request: SimpleNamespace(
            list_snapshots=lambda product_id=None: tuple(snapshots),
        ),
    )
    monkeypatch.setattr(
        admin_system,
        "_source_hugo_orchestrator",
        lambda request: SimpleNamespace(get_latest_chunk_records=_fake_get_latest_chunk_records),
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/coverage-gaps",
            params={"product_id": "aspose.words", "programming_language": "net"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["products_total"] == 1
    assert payload["surfaces_total"] == 1
    assert payload["partial_surfaces_total"] == 1
    product = payload["products"][0]
    assert product["product_id"] == "aspose.words"
    surface = product["surfaces"][0]
    assert surface["programming_language"] == "net"
    assert surface["status"] == "partial"
    assert surface["onboarding_priority"] == "medium"
    assert surface["ready_source_kinds"] == ["docs"]
    assert "apiref_not_ready" in surface["gap_badges"]
    assert surface["latest_stable_visible"] is False
    assert surface["executable_snippets_count"] == 1


def test_public_coverage_navigator_compacts_surface_cells_and_remediation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        return tuple(
            record
            for record in chunk_records
            if (product_id is None or record.product_id == product_id)
            and (
                programming_language is None
                or record.programming_language == programming_language
            )
            and (version is None or record.version == version)
        )

    docs_service = admin_system.AdminContentServiceHealthResponse(
        repo_id="aspose.words.docs",
        product_id="aspose.words",
        product_family="aspose",
        product_family_dir="Aspose.Words",
        source_kind="docs",
        git_url="https://example.invalid/aspose.words.docs.git",
        default_branch="master",
        submodule_path="source-repo-docs/Aspose.Words",
        layout_type="doc_locale/programming_language/content",
        layout_confidence=0.99,
        latest_operation_id="ing-op-1",
        latest_operation_status="completed",
        latest_operation_finished_at=datetime.now(tz=UTC),
        parse_warnings_count=0,
        failed_items_count=0,
        active_snapshot_id="snap-docs-net",
        active_snapshot_created_at=datetime.now(tz=UTC),
        active_scopes_count=1,
        supported_programming_languages=["net"],
        supported_versions=["25.3"],
        mcp_ready=True,
        onboarding_status="active",
        service_status="healthy",
        service_status_reason="active_snapshot_available",
        indicator_color="success",
        service_status_summary="Docs are ready.",
        fix_plan=["No action required."],
    )
    apiref_service = admin_system.AdminContentServiceHealthResponse(
        repo_id="aspose.words.apiref",
        product_id="aspose.words",
        product_family="aspose",
        product_family_dir="Aspose.Words",
        source_kind="apiref",
        git_url="https://example.invalid/aspose.words.apiref.git",
        default_branch="main",
        submodule_path="source-repo-apiref/Aspose.Words",
        layout_type="doc_locale/programming_language/namespace",
        layout_confidence=0.99,
        latest_operation_id="ing-op-2",
        latest_operation_status="completed",
        latest_operation_finished_at=datetime.now(tz=UTC),
        parse_warnings_count=0,
        failed_items_count=0,
        active_snapshot_id=None,
        active_snapshot_created_at=None,
        active_scopes_count=0,
        supported_programming_languages=[],
        supported_versions=[],
        mcp_ready=False,
        onboarding_status="ingested",
        service_status="warning",
        service_status_reason="completed_without_active_snapshot",
        indicator_color="warning",
        service_status_summary="API reference is registered but not published.",
        fix_plan=["Publish an active snapshot."],
    )
    snapshots = [
        SnapshotRecord(
            snapshot_id="snap-docs-net",
            product_id="aspose.words",
            programming_language="net",
            version="25.3",
            source_kind="docs",
            source_revision="rev-docs",
            status=SnapshotStatus.ACTIVE,
            indexed_chunks_count=12,
            created_at=datetime.now(tz=UTC),
        )
    ]
    chunk_records = (
        StageDChunkRecord(
            chunk_id="chunk-words-1",
            repo_id="aspose.words.docs",
            product_id="aspose.words",
            product_family="Aspose.Words",
            programming_language="net",
            version="25.3",
            source_kind="docs",
            doc_locale="en",
            doc_type="guide",
            symbol_fqn=None,
            title="Aspose.Words quickstart",
            section_path=("guide",),
            canonical_url="https://docs.aspose.com/words/net/quickstart/",
            section_anchor="#quickstart",
            source_path="en/net/getting-started/_index.md",
            source_revision="rev-docs",
            is_deprecated=False,
            has_code_example=True,
            chunk_type="guide_step",
            text="Use Aspose.Words in .NET.",
            tokens=110,
            checksum="words-checksum-1",
            executable_snippets=(
                StageDExecutableSnippet(
                    snippet_id="snippet-words-1",
                    language="csharp",
                    code="var doc = new Document();",
                    parent_canonical_url="https://docs.aspose.com/words/net/quickstart/",
                    parent_section_anchor="#quickstart",
                    parent_symbol_fqn=None,
                ),
            ),
        ),
    )

    monkeypatch.setattr(
        admin_system,
        "_collect_content_service_rows",
        lambda request, product_id=None, repo_id=None: [docs_service, apiref_service],
    )
    monkeypatch.setattr(
        admin_system,
        "_snapshot_registry",
        lambda request: SimpleNamespace(
            list_snapshots=lambda product_id=None: tuple(snapshots),
        ),
    )
    monkeypatch.setattr(
        admin_system,
        "_source_hugo_orchestrator",
        lambda request: SimpleNamespace(get_latest_chunk_records=_fake_get_latest_chunk_records),
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/coverage-navigator",
            params={"product_id": "aspose.words", "programming_language": "net"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["products_total"] == 1
    assert payload["surfaces_total"] == 1
    assert payload["partial_total"] == 1
    assert payload["available_programming_languages"] == ["net"]
    surface = payload["surfaces"][0]
    assert surface["surface_id"] == "aspose.words:net"
    assert surface["overall_status"] == "partial"
    assert surface["onboarding_priority"] == "medium"
    assert surface["executable_snippets_count"] == 1
    assert "apiref_not_ready" in surface["gap_badges"]
    assert any(
        cell["source_kind"] == "docs" and cell["status"] == "ready"
        for cell in surface["cells"]
    )
    assert any(
        cell["source_kind"] == "apiref" and cell["status"] == "gap"
        for cell in surface["cells"]
    )
    assert any("Publish an active apiref snapshot" in step for step in surface["remediation"])
    assert any(action["label"] == "Capability explorer" for action in surface["actions"])


def test_public_trust_board_rolls_up_explainable_scope_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(tz=UTC)
    monkeypatch.setattr(
        admin_system,
        "_build_public_coverage_navigator",
        lambda *_args, **_kwargs: admin_system.PublicCoverageNavigatorResponse(
            filters={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "source_kind": None,
                "version": None,
            },
            products_total=1,
            surfaces_total=1,
            ready_total=0,
            partial_total=1,
            registered_only_total=0,
            available_products=["aspose.ocr"],
            available_programming_languages=["net"],
            available_source_kinds=["docs", "apiref"],
            available_versions=["25.3"],
            status_summary=(
                "Navigator surfaced 1 scope row(s): ready=0, partial=1, "
                "registered_only=0."
            ),
            surfaces=[
                admin_system.PublicCoverageNavigatorSurfaceResponse(
                    surface_id="aspose.ocr:net",
                    product_id="aspose.ocr",
                    product_name="Aspose.OCR",
                    product_family="Aspose",
                    programming_language="net",
                    overall_status="partial",
                    onboarding_priority="medium",
                    latest_visible_versions=["25.3"],
                    executable_snippets_count=2,
                    gap_badges=["apiref_not_ready"],
                    summary=(
                        "Docs are live, but API reference still needs a "
                        "published active snapshot."
                    ),
                    remediation=["Publish an active apiref snapshot for net."],
                    cells=[
                        admin_system.PublicCoverageNavigatorCellResponse(
                            source_kind="docs",
                            status="ready",
                            active_versions=["25.3"],
                            service_reason=None,
                        ),
                        admin_system.PublicCoverageNavigatorCellResponse(
                            source_kind="apiref",
                            status="gap",
                            active_versions=["25.3"],
                            service_reason="completed_without_active_snapshot",
                        ),
                    ],
                    actions=[
                        admin_system.PublicCapabilityActionResponse(
                            label="Open coverage navigator",
                            href="/integrations?product_id=aspose.ocr&language=net#coverage-navigator",
                        )
                    ],
                )
            ],
            generated_at=now,
        ),
    )
    monkeypatch.setattr(
        admin_system,
        "_build_public_release_freshness",
        lambda *_args, **_kwargs: admin_system.PublicReleaseFreshnessResponse(
            product_id="aspose.ocr",
            programming_language="net",
            requested_version=None,
            resolved_version="25.2",
            newest_available_version="25.3",
            available_versions=["25.3", "25.2"],
            latest_active_snapshot_at=now - timedelta(days=4),
            services=[],
            release_features=[
                admin_system.PublicReleaseFeaturePreviewResponse(
                    kind="release_feature",
                    summary="Added improved OCR table extraction heuristics.",
                    symbol_fqn=None,
                    version="25.3",
                    source_kind="docs",
                    canonical_url="https://example.invalid/releases/25.3",
                    section_anchor="#tables",
                )
            ],
            status_summary=(
                "Newest release is visible, but the selected scope still "
                "resolves to 25.2."
            ),
            generated_at=now,
        ),
    )
    monkeypatch.setattr(
        admin_system,
        "_analytics_service",
        lambda _request: SimpleNamespace(
            usefulness_summary=lambda **_kwargs: SimpleNamespace(
                total_feedback=5,
                useful_share=0.8,
                negative_share=0.2,
                by_reason_code={"missing_steps": 2},
            ),
            list_issue_reports=lambda **_kwargs: (SimpleNamespace(issue_id="issue-1"),),
        ),
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/trust-signals",
            params={"product_id": "aspose.ocr", "programming_language": "net"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "aspose.ocr"
    assert payload["programming_language"] == "net"
    assert payload["trust_posture"] == "guarded"
    assert payload["watch_total"] == 3
    assert payload["weak_total"] == 0
    cards = {item["signal_id"]: item for item in payload["scorecards"]}
    assert set(cards) == {"readiness", "freshness", "feedback"}
    assert cards["readiness"]["status"] == "watch"
    assert any(
        action["label"] == "Open coverage navigator"
        for action in cards["readiness"]["actions"]
    )
    assert any("newest_visible_version=25.3" in item for item in cards["freshness"]["evidence"])
    assert any("feedback_total=5" in item for item in cards["feedback"]["evidence"])


def test_public_capability_explorer_rolls_up_surface_actions_and_snippet_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        return tuple(
            record
            for record in chunk_records
            if (product_id is None or record.product_id == product_id)
            and (
                programming_language is None
                or record.programming_language == programming_language
            )
            and (version is None or record.version == version)
        )

    docs_service = admin_system.AdminContentServiceHealthResponse(
        repo_id="aspose.words.docs",
        product_id="aspose.words",
        product_family="aspose",
        product_family_dir="Aspose.Words",
        source_kind="docs",
        git_url="https://example.invalid/aspose.words.docs.git",
        default_branch="master",
        submodule_path="source-repo-docs/Aspose.Words",
        layout_type="doc_locale/programming_language/content",
        layout_confidence=0.99,
        latest_operation_id="ing-op-1",
        latest_operation_status="completed",
        latest_operation_finished_at=datetime.now(tz=UTC),
        parse_warnings_count=0,
        failed_items_count=0,
        active_snapshot_id="snap-docs-net",
        active_snapshot_created_at=datetime.now(tz=UTC),
        active_scopes_count=1,
        supported_programming_languages=["net"],
        supported_versions=["25.3"],
        mcp_ready=True,
        onboarding_status="active",
        service_status="healthy",
        service_status_reason="active_snapshot_available",
        indicator_color="success",
        service_status_summary="Docs are ready.",
        fix_plan=["No action required."],
    )
    apiref_service = admin_system.AdminContentServiceHealthResponse(
        repo_id="aspose.words.apiref",
        product_id="aspose.words",
        product_family="aspose",
        product_family_dir="Aspose.Words",
        source_kind="apiref",
        git_url="https://example.invalid/aspose.words.apiref.git",
        default_branch="main",
        submodule_path="source-repo-apiref/Aspose.Words",
        layout_type="doc_locale/programming_language/namespace",
        layout_confidence=0.99,
        latest_operation_id="ing-op-2",
        latest_operation_status="completed",
        latest_operation_finished_at=datetime.now(tz=UTC),
        parse_warnings_count=0,
        failed_items_count=0,
        active_snapshot_id=None,
        active_snapshot_created_at=None,
        active_scopes_count=0,
        supported_programming_languages=[],
        supported_versions=[],
        mcp_ready=False,
        onboarding_status="ingested",
        service_status="warning",
        service_status_reason="completed_without_active_snapshot",
        indicator_color="warning",
        service_status_summary="API reference is registered but not published.",
        fix_plan=["Publish an active snapshot."],
    )
    snapshots = [
        SnapshotRecord(
            snapshot_id="snap-docs-net",
            product_id="aspose.words",
            programming_language="net",
            version="25.3",
            source_kind="docs",
            source_revision="rev-docs",
            status=SnapshotStatus.ACTIVE,
            indexed_chunks_count=12,
            created_at=datetime.now(tz=UTC),
        )
    ]
    chunk_records = (
        StageDChunkRecord(
            chunk_id="chunk-words-1",
            repo_id="aspose.words.docs",
            product_id="aspose.words",
            product_family="Aspose.Words",
            programming_language="net",
            version="25.3",
            source_kind="docs",
            doc_locale="en",
            doc_type="guide",
            symbol_fqn=None,
            title="Aspose.Words quickstart",
            section_path=("guide",),
            canonical_url="https://docs.aspose.com/words/net/quickstart/",
            section_anchor="#quickstart",
            source_path="en/net/getting-started/_index.md",
            source_revision="rev-docs",
            is_deprecated=False,
            has_code_example=True,
            chunk_type="guide_step",
            text="Use Aspose.Words in .NET.",
            tokens=110,
            checksum="words-checksum-1",
            executable_snippets=(
                StageDExecutableSnippet(
                    snippet_id="snippet-words-1",
                    language="csharp",
                    code="var doc = new Document();",
                    parent_canonical_url="https://docs.aspose.com/words/net/quickstart/",
                    parent_section_anchor="#quickstart",
                    parent_symbol_fqn=None,
                ),
            ),
        ),
    )

    monkeypatch.setattr(
        admin_system,
        "_collect_content_service_rows",
        lambda request, product_id=None, repo_id=None: [docs_service, apiref_service],
    )
    monkeypatch.setattr(
        admin_system,
        "_snapshot_registry",
        lambda request: SimpleNamespace(
            list_snapshots=lambda product_id=None: tuple(snapshots),
        ),
    )
    monkeypatch.setattr(
        admin_system,
        "_source_hugo_orchestrator",
        lambda request: SimpleNamespace(get_latest_chunk_records=_fake_get_latest_chunk_records),
    )
    monkeypatch.setattr(
        admin_system,
        "_build_public_release_freshness",
        lambda request, product_id, programming_language, version, top_k: (
            admin_system.PublicReleaseFreshnessResponse(
                product_id=product_id,
                programming_language=programming_language,
                requested_version=version,
                resolved_version="25.3",
                newest_available_version="25.3",
                available_versions=["25.3", "latest-stable"],
                latest_active_snapshot_at=datetime.now(tz=UTC),
                services=[],
                release_features=[],
                status_summary="Freshness is available.",
                generated_at=datetime.now(tz=UTC),
            )
        ),
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/capabilities",
            params={"product_id": "aspose.words", "programming_language": "net"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["products_total"] == 1
    assert payload["capabilities_total"] == 1
    assert payload["partial_total"] == 1
    item = payload["items"][0]
    assert item["capability_id"] == "aspose.words:net"
    assert item["status"] == "partial"
    assert item["freshness_label"] == "not-ready"
    assert item["snippet_titles"] == ["Aspose.Words quickstart"]
    assert any(action["href"].endswith("#coverage-gap-tracker") for action in item["actions"])


def test_public_scope_compare_board_highlights_stronger_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(tz=UTC)

    def _fake_trust_board(
        _request: object,
        *,
        product_id: str,
        programming_language: str | None,
        version: str | None,
    ) -> admin_system.PublicTrustSignalsBoardResponse:
        if programming_language == "net":
            trust_posture = "high"
            scorecards = [
                admin_system.PublicTrustSignalScorecardResponse(
                    signal_id="readiness",
                    title="Scope readiness",
                    status="strong",
                    score=90,
                    summary="Primary scope is fully ready.",
                    evidence=["ready=docs+apiref"],
                    actions=[],
                ),
                admin_system.PublicTrustSignalScorecardResponse(
                    signal_id="freshness",
                    title="Release freshness",
                    status="strong",
                    score=88,
                    summary="Freshness is healthy.",
                    evidence=["resolved=25.3"],
                    actions=[],
                ),
                admin_system.PublicTrustSignalScorecardResponse(
                    signal_id="feedback",
                    title="Developer feedback",
                    status="watch",
                    score=68,
                    summary="Feedback is mostly positive.",
                    evidence=["feedback_total=3"],
                    actions=[],
                ),
            ]
        else:
            trust_posture = "guarded"
            scorecards = [
                admin_system.PublicTrustSignalScorecardResponse(
                    signal_id="readiness",
                    title="Scope readiness",
                    status="watch",
                    score=62,
                    summary="Compared scope is partial.",
                    evidence=["ready=docs only"],
                    actions=[],
                ),
                admin_system.PublicTrustSignalScorecardResponse(
                    signal_id="freshness",
                    title="Release freshness",
                    status="watch",
                    score=56,
                    summary="Compared scope lags behind.",
                    evidence=["resolved=25.2"],
                    actions=[],
                ),
                admin_system.PublicTrustSignalScorecardResponse(
                    signal_id="feedback",
                    title="Developer feedback",
                    status="watch",
                    score=60,
                    summary="Feedback is still guarded.",
                    evidence=["feedback_total=1"],
                    actions=[],
                ),
            ]
        return admin_system.PublicTrustSignalsBoardResponse(
            product_id=product_id,
            programming_language=programming_language,
            requested_version=version,
            resolved_version=version or "25.3",
            trust_posture=trust_posture,
            strong_total=sum(1 for item in scorecards if item.status == "strong"),
            watch_total=sum(1 for item in scorecards if item.status == "watch"),
            weak_total=0,
            status_summary=f"{product_id}/{programming_language}: {trust_posture}",
            explainability=["compare scope evidence"],
            scorecards=scorecards,
            generated_at=now,
        )

    def _fake_coverage_navigator(
        _request: object,
        *,
        product_id: str | None,
        programming_language: str | None,
        source_kind: str | None,
        version: str | None,
    ) -> admin_system.PublicCoverageNavigatorResponse:
        snippet_count = 5 if programming_language == "net" else 2
        return admin_system.PublicCoverageNavigatorResponse(
            filters={
                "product_id": product_id,
                "programming_language": programming_language,
                "source_kind": source_kind,
                "version": version,
            },
            products_total=1,
            surfaces_total=1,
            ready_total=1 if programming_language == "net" else 0,
            partial_total=0 if programming_language == "net" else 1,
            registered_only_total=0,
            available_products=[product_id or "aspose.ocr"],
            available_programming_languages=[programming_language or "net"],
            available_source_kinds=["docs", "apiref"],
            available_versions=[version or "25.3"],
            status_summary="compare navigator",
            surfaces=[
                admin_system.PublicCoverageNavigatorSurfaceResponse(
                    surface_id=f"{product_id}:{programming_language}",
                    product_id=product_id or "aspose.ocr",
                    product_name="Aspose.OCR",
                    product_family="Aspose",
                    programming_language=programming_language or "net",
                    overall_status="ready" if programming_language == "net" else "partial",
                    onboarding_priority="low" if programming_language == "net" else "medium",
                    latest_visible_versions=[version or "25.3"],
                    executable_snippets_count=snippet_count,
                    gap_badges=[],
                    summary="compare surface",
                    remediation=[],
                    cells=[],
                    actions=[],
                )
            ],
            generated_at=now,
        )

    monkeypatch.setattr(admin_system, "_build_public_trust_signals_board", _fake_trust_board)
    monkeypatch.setattr(admin_system, "_build_public_coverage_navigator", _fake_coverage_navigator)

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/compare-board",
            params={
                "left_product_id": "aspose.ocr",
                "left_programming_language": "net",
                "right_product_id": "aspose.ocr",
                "right_programming_language": "java",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["preferred_side"] == "left"
    assert (
        payload["left_scope"]["average_signal_score"]
        > payload["right_scope"]["average_signal_score"]
    )
    metrics = {item["metric_id"]: item for item in payload["metrics"]}
    assert metrics["readiness"]["preferred_side"] == "left"
    assert metrics["snippet_evidence"]["left_score"] == 5
    assert metrics["snippet_evidence"]["right_score"] == 2


def test_public_troubleshooting_builds_paths_from_self_test_triage_and_request_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        admin_system,
        "_build_public_mcp_self_test",
        lambda request, product_id, programming_language, client_id, transport: (
            admin_system.PublicMCPSelfTestResponse(
                product_id=product_id,
                programming_language=programming_language,
                client_id=client_id,
                transport=transport,
                status="partial",
                status_summary=(
                    "MCP can be used now, but coverage or runtime quality is only "
                    "partial for this scope."
                ),
                docs_ready_count=1,
                apiref_ready_count=0,
                total_ready_services=1,
                total_registered_services=2,
                snippet_count=0,
                available_programming_languages=["net"],
                available_versions=["25.1"],
                checks=[],
                fix_plan=["Run self-test first.", "Then open starter packs."],
                config_export_url="http://testserver/integrations",
                status_page_url="http://testserver/status",
                mcp_url="http://testserver/mcp/v1/streamable-http",
                sample_prompt="Use MCP.",
                generated_at=datetime.now(tz=UTC),
            )
        ),
    )
    monkeypatch.setattr(
        admin_system,
        "_build_public_content_triage",
        lambda request, product_id, repo_id, severity, source_kind, stale_after_days, limit: (
            admin_system.PublicContentTriageResponse(
                filters={
                    "product_id": product_id,
                    "repo_id": repo_id,
                    "severity": severity,
                    "source_kind": source_kind,
                },
                stale_after_days=stale_after_days,
                total_items=1,
                critical_total=1,
                warning_total=0,
                info_total=0,
                status_summary="Found 1 triage gap(s): critical=1, warning=0, info=0.",
                items=[
                    admin_system.PublicContentTriageGapResponse(
                        gap_id="gap-1",
                        severity="critical",
                        signal_type="no_index_data",
                        repo_id="aspose.ocr.apiref",
                        product_id="aspose.ocr",
                        source_kind="apiref",
                        service_status="warning",
                        service_status_reason="completed_without_active_snapshot",
                        mcp_ready=False,
                        indexed_chunks_count=0,
                        executable_snippets_count=0,
                        active_snapshot_created_at=None,
                        stale_days=None,
                        summary="API reference is not published yet.",
                        fix_plan=["Publish API reference snapshot."],
                    )
                ],
                generated_at=datetime.now(tz=UTC),
            )
        ),
    )

    class _FakeAnalyticsService:
        def get_record(self, request_id: str):
            if request_id != "req-query-1":
                return None
            return SimpleNamespace(
                request_id=request_id,
                product_id="aspose.ocr",
                programming_language="net",
                outcome="partial",
                result_count=0,
                confidence=0.22,
                zero_result_reason="no_index_data",
                fallback_reason="latest_stable_missing",
                warning_codes=("no_index_data", "freshness_gap"),
            )

        def list_usefulness_feedback(self, *, request_id: str, **kwargs):
            return (SimpleNamespace(rating="not_useful"),) if request_id == "req-query-1" else ()

        def list_issue_reports(self, *, request_id: str, **kwargs):
            return (
                (SimpleNamespace(issue_type="missing_docs"),)
                if request_id == "req-query-1"
                else ()
            )

    monkeypatch.setattr(admin_system, "_analytics_service", lambda request: _FakeAnalyticsService())

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/troubleshooting",
            params={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "client_id": "cursor",
                "transport": "streamable-http",
                "request_id": "req-query-1",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["self_test_status"] == "partial"
    assert payload["critical_gap_total"] == 1
    assert payload["request_diagnostics"]["request_id"] == "req-query-1"
    assert payload["request_diagnostics"]["result_count"] == 0
    path_ids = {item["path_id"] for item in payload["paths"]}
    assert "connection-readiness" in path_ids
    assert "content-coverage-gap" in path_ids
    assert "request-quality-recovery" in path_ids


def test_public_release_adoption_rolls_up_freshness_breaking_changes_and_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        admin_system,
        "_build_public_release_freshness",
        lambda request, product_id, programming_language, version, top_k: (
            admin_system.PublicReleaseFreshnessResponse(
                product_id=product_id,
                programming_language=programming_language,
                requested_version=version,
                resolved_version="25.2",
                newest_available_version="25.3",
                available_versions=["25.3", "25.2", "25.1"],
                latest_active_snapshot_at=datetime.now(tz=UTC),
                services=[],
                release_features=[
                    admin_system.PublicReleaseFeaturePreviewResponse(
                        kind="release-note",
                        summary="Added improved table extraction guidance.",
                        symbol_fqn=None,
                        version="25.3",
                        source_kind="docs",
                        canonical_url="https://docs.example/releases/25.3",
                        section_anchor="#tables",
                    )
                ],
                status_summary="Freshness is usable for this scope.",
                generated_at=datetime.now(tz=UTC),
            )
        ),
    )

    class _FakePublicQueryService:
        def list_latest_release_features(self, *, request):
            return ListLatestReleaseFeaturesResponse(
                product_id=request.product_id,
                language=request.language,
                resolved_version=request.version or "25.3",
                items=[
                    ReleaseFeatureItemResponse(
                        kind="release-note",
                        summary="Added improved table extraction guidance.",
                        symbol_fqn=None,
                        version="25.3",
                        source_kind="docs",
                        citation=ReleaseFeatureCitationResponse(
                            canonical_url="https://docs.example/releases/25.3",
                            section_anchor="#tables",
                        ),
                    )
                ],
                guardrails=["Validate symbol contracts before upgrading code."],
            )

        def list_breaking_changes(self, *, request):
            total = 4 if request.from_version == "25.1" else 1
            return ListBreakingChangesResponse(
                items=[
                    BreakingChangeItemResponse(
                        type="signature-change",
                        symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
                        from_version=request.from_version,
                        to_version=request.to_version,
                        description="RecognizeImage now requires an options object.",
                        migration_hint="Pass RecognitionSettings explicitly.",
                        citation=BreakingChangeCitationResponse(
                            canonical_url="https://docs.example/breaking",
                            section_anchor="#recognize-image",
                        ),
                    )
                ],
                page=request.page,
                page_size=request.page_size,
                total=total,
            )

    monkeypatch.setattr(
        admin_system,
        "_public_query_service",
        lambda request: _FakePublicQueryService(),
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/release-adoption",
            params={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "version": "25.1",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommended_to_version"] == "25.3"
    assert payload["recommended_from_version"] == "25.1"
    assert payload["breaking_changes"]["total"] == 4
    assert payload["latest_release"]["resolved_version"] == "25.3"
    assert payload["compare_ranges"][0]["from_version"] == "25.2"
    assert payload["status"] == "watch"


def test_public_use_case_gallery_returns_curated_cards_with_live_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        admin_system,
        "_build_public_mcp_self_test",
        lambda request, product_id, programming_language, client_id, transport: (
            admin_system.PublicMCPSelfTestResponse(
                product_id=product_id,
                programming_language=programming_language,
                client_id=client_id,
                transport=transport,
                status="ready",
                status_summary="ready",
                docs_ready_count=1,
                apiref_ready_count=1,
                total_ready_services=2,
                total_registered_services=2,
                snippet_count=2,
                available_programming_languages=["net"],
                available_versions=["25.1"],
                checks=[],
                fix_plan=["Run query."],
                config_export_url="http://testserver/integrations",
                status_page_url="http://testserver/status",
                mcp_url="http://testserver/mcp/v1/streamable-http",
                sample_prompt="Use MCP.",
                generated_at=datetime.now(tz=UTC),
            )
        ),
    )
    monkeypatch.setattr(
        admin_system,
        "_build_public_snippet_explorer",
        lambda request, product_id, programming_language, version, source_kind, limit: (
            admin_system.PublicSnippetExplorerResponse(
                product_id=product_id,
                programming_language=programming_language,
                version=version,
                source_kind=source_kind,
                total_snippets=2,
                items=[
                    admin_system.PublicSnippetItemResponse(
                        snippet_id="snippet-table",
                        product_id=product_id or "aspose.ocr",
                        programming_language=programming_language or "net",
                        version="25.1",
                        source_kind="docs",
                        doc_type="guide",
                        title="Recognize tables quickstart",
                        canonical_url="https://docs.example/table",
                        section_anchor="#quickstart",
                        symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeTables",
                        snippet_language="csharp",
                        code="var result = api.RecognizeTables(\"table.png\");",
                        source_revision="rev-1",
                        repo_id="aspose.ocr.docs",
                    ),
                    admin_system.PublicSnippetItemResponse(
                        snippet_id="snippet-text",
                        product_id=product_id or "aspose.ocr",
                        programming_language=programming_language or "net",
                        version="25.1",
                        source_kind="docs",
                        doc_type="guide",
                        title="Recognize image quickstart",
                        canonical_url="https://docs.example/text",
                        section_anchor="#quickstart",
                        symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
                        snippet_language="csharp",
                        code="var result = api.RecognizeImage(\"scan.png\");",
                        source_revision="rev-1",
                        repo_id="aspose.ocr.docs",
                    ),
                ],
                generated_at=datetime.now(tz=UTC),
            )
        ),
    )
    monkeypatch.setattr(
        admin_system,
        "_build_public_mcp_config_export",
        lambda request, product_id, transport: admin_system.PublicMCPConfigExportResponse(
            server_name="aspose-ocr",
            product_id=product_id or "aspose.ocr",
            transport=transport,
            mcp_url="http://testserver/mcp/v1/streamable-http",
            sample_prompt="Use MCP for OCR.",
            clients=[],
            generated_at=datetime.now(tz=UTC),
        ),
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/use-cases",
            params={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "client_id": "cursor",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["product_id"] == "aspose.ocr"
    assert len(payload["items"]) >= 3
    first_item = payload["items"][0]
    assert first_item["client_notes"][0]["client_id"] == "cursor"
    assert first_item["evidence"][0]["evidence_type"] == "snippet"
    assert any(action["label"] == "Open guided journeys" for action in first_item["actions"])


def test_public_topology_policy_returns_runtime_profile() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/topology")

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] in {"dev", "staging", "prod"}
    assert payload["qdrant"]["shard_number"] >= 1
    assert payload["opensearch"]["number_of_shards"] >= 1
    assert isinstance(payload["summary"], str)


def test_public_mcp_config_export_rejects_unsupported_transport() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/mcp-configs",
            params={"transport": "stdio"},
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "INVALID_TRANSPORT"


def test_public_snippet_explorer_returns_public_examples() -> None:
    app = create_app()
    orchestrator = app.state.source_hugo_normalization_orchestrator

    def _patched_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        records = (
            StageDChunkRecord(
                chunk_id="chunk-1",
                repo_id="aspose.ocr.docs",
                product_id="aspose.ocr",
                product_family="Aspose.OCR",
                programming_language="net",
                version="25.1",
                source_kind="docs",
                doc_locale="en",
                doc_type="guide",
                symbol_fqn=None,
                title="Recognize image quickstart",
                section_path=("guide",),
                canonical_url="https://docs.aspose.com/ocr/net/recognize-image/",
                section_anchor="#quickstart",
                source_path="guide/recognize-image.md",
                source_revision="rev-1",
                is_deprecated=False,
                has_code_example=True,
                chunk_type="guide_step",
                text="Use Aspose OCR with a simple quickstart.",
                tokens=120,
                checksum="checksum-1",
                executable_snippets=(
                    StageDExecutableSnippet(
                        snippet_id="snippet-1",
                        language="csharp",
                        code='var result = api.RecognizeImage("sample.png");',
                        parent_canonical_url="https://docs.aspose.com/ocr/net/recognize-image/",
                        parent_section_anchor="#quickstart",
                        parent_symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
                    ),
                ),
            ),
        )
        return tuple(
            record
            for record in records
            if (product_id is None or record.product_id == product_id)
            and (
                programming_language is None
                or record.programming_language == programming_language
            )
            and (version is None or record.version == version)
        )

    orchestrator.get_latest_chunk_records = _patched_get_latest_chunk_records  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.get(
            "/v1/snippets",
            params={"product_id": "aspose.ocr", "programming_language": "net"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "aspose.ocr"
    assert payload["programming_language"] == "net"
    assert payload["total_snippets"] == 1
    assert payload["items"][0]["snippet_id"] == "snippet-1"
    assert "RecognizeImage" in payload["items"][0]["code"]


def test_public_mcp_self_test_reports_ready_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_check_dependencies(
        *_: object,
        **__: object,
    ) -> admin_system.readiness.DependencyResults:
        return {
            "postgres": (True, "reachable"),
            "redis": (True, "reachable"),
            "qdrant": (True, "reachable"),
            "opensearch": (True, "reachable"),
        }

    def _fake_collect_content_service_rows(
        request: object,
        *,
        product_id: str | None = None,
        repo_id: str | None = None,
    ) -> list[admin_system.AdminContentServiceHealthResponse]:
        del request, repo_id
        if product_id != "aspose.ocr":
            return []
        return [
            admin_system.AdminContentServiceHealthResponse(
                repo_id="aspose.ocr.docs",
                product_id="aspose.ocr",
                product_family="Aspose.OCR",
                product_family_dir="Aspose.OCR",
                source_kind="docs",
                git_url="https://github.com/aspose-ocr/Aspose.OCR-Documentation",
                default_branch="master",
                submodule_path="source-repo-docs/Aspose.OCR",
                layout_type="programming_language/content",
                layout_confidence=0.99,
                latest_operation_id="op-1",
                latest_operation_status="completed",
                latest_operation_finished_at=None,
                parse_warnings_count=0,
                failed_items_count=0,
                active_snapshot_id="snap-docs",
                active_snapshot_created_at=None,
                active_scopes_count=1,
                supported_programming_languages=["net"],
                supported_versions=["latest-stable"],
                mcp_ready=True,
                onboarding_status="active",
                service_status="healthy",
                service_status_reason="active_snapshot_available",
                indicator_color="green",
                service_status_summary="Docs ready.",
                fix_plan=["No action required."],
            ),
            admin_system.AdminContentServiceHealthResponse(
                repo_id="aspose.ocr.apiref",
                product_id="aspose.ocr",
                product_family="Aspose.OCR",
                product_family_dir="Aspose.OCR",
                source_kind="apiref",
                git_url="https://github.com/aspose-ocr/Aspose.OCR-API-References.git",
                default_branch="main",
                submodule_path="source-repo-apiref/Aspose.OCR",
                layout_type="doc_locale/programming_language/namespace",
                layout_confidence=0.99,
                latest_operation_id="op-2",
                latest_operation_status="completed",
                latest_operation_finished_at=None,
                parse_warnings_count=0,
                failed_items_count=0,
                active_snapshot_id="snap-apiref",
                active_snapshot_created_at=None,
                active_scopes_count=1,
                supported_programming_languages=["net"],
                supported_versions=["latest-stable"],
                mcp_ready=True,
                onboarding_status="active",
                service_status="healthy",
                service_status_reason="active_snapshot_available",
                indicator_color="green",
                service_status_summary="API reference ready.",
                fix_plan=["No action required."],
            ),
        ]

    monkeypatch.setattr(admin_system.readiness, "check_dependencies", _fake_check_dependencies)
    monkeypatch.setattr(
        admin_system,
        "_collect_content_service_rows",
        _fake_collect_content_service_rows,
    )

    app = create_app()
    orchestrator = app.state.source_hugo_normalization_orchestrator

    def _patched_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        del version
        if product_id != "aspose.ocr" or programming_language != "net":
            return ()
        return (
            StageDChunkRecord(
                chunk_id="chunk-1",
                repo_id="aspose.ocr.docs",
                product_id="aspose.ocr",
                product_family="Aspose.OCR",
                programming_language="net",
                version="latest-stable",
                source_kind="docs",
                doc_locale="en",
                doc_type="guide",
                symbol_fqn=None,
                title="Recognize image quickstart",
                section_path=("guide",),
                canonical_url="https://docs.aspose.com/ocr/net/recognize-image/",
                section_anchor="#quickstart",
                source_path="guide/recognize-image.md",
                source_revision="rev-1",
                is_deprecated=False,
                has_code_example=True,
                chunk_type="guide_step",
                text="Use Aspose OCR with a simple quickstart.",
                tokens=120,
                checksum="checksum-1",
                executable_snippets=(
                    StageDExecutableSnippet(
                        snippet_id="snippet-1",
                        language="csharp",
                        code='var result = api.RecognizeImage("sample.png");',
                        parent_canonical_url="https://docs.aspose.com/ocr/net/recognize-image/",
                        parent_section_anchor="#quickstart",
                        parent_symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
                    ),
                ),
            ),
        )

    orchestrator.get_latest_chunk_records = _patched_get_latest_chunk_records  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/self-test",
            params={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "client_id": "cursor",
                "transport": "streamable-http",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["docs_ready_count"] == 1
    assert payload["apiref_ready_count"] == 1
    assert payload["snippet_count"] == 1
    assert payload["client_id"] == "cursor"
    assert any(
        item["check_id"] == "content-readiness" and item["status"] == "pass"
        for item in payload["checks"]
    )


def test_public_mcp_self_test_reports_unknown_product() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/self-test",
            params={
                "product_id": "unknown.product",
                "programming_language": "net",
                "client_id": "cursor",
                "transport": "streamable-http",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["total_registered_services"] == 0
    assert payload["checks"][0]["check_id"] == "product-registered"
    assert payload["checks"][0]["status"] == "fail"


def test_public_mcp_self_test_rejects_unsupported_client() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/self-test",
            params={
                "product_id": "aspose.ocr",
                "client_id": "windsurf",
            },
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "INVALID_CLIENT_ID"


def test_public_release_freshness_returns_snapshot_and_feature_visibility() -> None:
    app = create_app()
    snapshot_registry = app.state.snapshot_registry
    snapshot_registry.list_snapshots = lambda: (
        admin_system.SnapshotRecord(
            snapshot_id="snap-docs",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            source_kind="docs",
            source_revision="rev-docs-1",
            status=admin_system.SnapshotStatus.ACTIVE,
            indexed_chunks_count=12,
            created_at=admin_system.datetime(2026, 3, 10, tzinfo=admin_system.UTC),
        ),
        admin_system.SnapshotRecord(
            snapshot_id="snap-apiref",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            source_kind="apiref",
            source_revision="rev-api-1",
            status=admin_system.SnapshotStatus.ACTIVE,
            indexed_chunks_count=28,
            created_at=admin_system.datetime(2026, 3, 10, 1, tzinfo=admin_system.UTC),
        ),
    )
    orchestrator = app.state.source_hugo_normalization_orchestrator

    def _patched_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        del version
        if product_id != "aspose.ocr" or programming_language != "net":
            return ()
        return (
            StageDChunkRecord(
                chunk_id="release-1",
                repo_id="aspose.ocr.docs",
                product_id="aspose.ocr",
                product_family="Aspose.OCR",
                programming_language="net",
                version="25.1",
                source_kind="docs",
                doc_locale="en",
                doc_type="release_note",
                symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
                title="What's new in 25.1",
                section_path=("release-notes",),
                canonical_url="https://docs.aspose.com/ocr/net/release-notes/25-1/",
                section_anchor="#feature-1",
                source_path="release-notes/25-1.md",
                source_revision="rev-docs-1",
                is_deprecated=False,
                has_code_example=False,
                chunk_type="release_note",
                text="What's new: improved table recognition and preprocessing quality.",
                tokens=90,
                checksum="release-checksum-1",
                executable_snippets=(),
            ),
        )

    orchestrator.get_latest_chunk_records = _patched_get_latest_chunk_records  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/freshness",
            params={"product_id": "aspose.ocr", "programming_language": "net"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "aspose.ocr"
    assert payload["resolved_version"] == "25.1"
    assert payload["newest_available_version"] == "25.1"
    assert len(payload["services"]) == 2
    assert payload["release_features"][0]["version"] == "25.1"
    assert "improved table recognition" in payload["release_features"][0]["summary"].lower()


def test_public_content_triage_returns_stale_and_missing_index_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    def _fake_collect_content_service_rows(
        request: object,
        *,
        product_id: str | None = None,
        repo_id: str | None = None,
    ) -> list[admin_system.AdminContentServiceHealthResponse]:
        del request
        rows = [
            admin_system.AdminContentServiceHealthResponse(
                repo_id="aspose.ocr.docs",
                product_id="aspose.ocr",
                product_family="Aspose.OCR",
                product_family_dir="Aspose.OCR",
                source_kind="docs",
                git_url="https://example.invalid/docs.git",
                default_branch="master",
                submodule_path="source-repo-docs/Aspose.OCR",
                layout_type="programming_language/content",
                layout_confidence=0.99,
                latest_operation_id="op-docs",
                latest_operation_status="completed",
                latest_operation_finished_at=None,
                parse_warnings_count=0,
                failed_items_count=0,
                active_snapshot_id=None,
                active_snapshot_created_at=None,
                active_scopes_count=0,
                supported_programming_languages=["net"],
                supported_versions=["25.1"],
                mcp_ready=False,
                onboarding_status="ingested",
                service_status="warning",
                service_status_reason="completed_without_active_snapshot",
                indicator_color="warning",
                service_status_summary=(
                    "Content was processed but no active snapshot is serving "
                    "MCP traffic."
                ),
                fix_plan=["Publish a snapshot.", "Verify the new snapshot becomes active."],
            ),
            admin_system.AdminContentServiceHealthResponse(
                repo_id="aspose.ocr.apiref",
                product_id="aspose.ocr",
                product_family="Aspose.OCR",
                product_family_dir="Aspose.OCR",
                source_kind="apiref",
                git_url="https://example.invalid/apiref.git",
                default_branch="main",
                submodule_path="source-repo-apiref/Aspose.OCR",
                layout_type="doc_locale/programming_language/namespace",
                layout_confidence=0.99,
                latest_operation_id="op-apiref",
                latest_operation_status="completed",
                latest_operation_finished_at=None,
                parse_warnings_count=0,
                failed_items_count=0,
                active_snapshot_id="snap-apiref",
                active_snapshot_created_at=datetime.now(tz=UTC) - timedelta(days=45),
                active_scopes_count=1,
                supported_programming_languages=["net"],
                supported_versions=["25.1"],
                mcp_ready=True,
                onboarding_status="active",
                service_status="healthy",
                service_status_reason="active_snapshot_available",
                indicator_color="success",
                service_status_summary="Active snapshot is published and ready.",
                fix_plan=["No action required."],
            ),
        ]
        return [
            row
            for row in rows
            if (product_id is None or row.product_id == product_id)
            and (repo_id is None or row.repo_id == repo_id)
        ]

    monkeypatch.setattr(
        admin_system,
        "_collect_content_service_rows",
        _fake_collect_content_service_rows,
    )

    def _patched_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        del programming_language, version
        if product_id != "aspose.ocr":
            return ()
        return (
            StageDChunkRecord(
                chunk_id="chunk-apiref-1",
                repo_id="aspose.ocr.apiref",
                product_id="aspose.ocr",
                product_family="Aspose.OCR",
                programming_language="net",
                version="25.1",
                source_kind="apiref",
                doc_locale="en",
                doc_type="api_reference",
                symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
                title="RecognizeImage",
                section_path=("api",),
                canonical_url="https://reference.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/",
                section_anchor="#recognizeimage",
                source_path="api/recognizeimage.md",
                source_revision="rev-api-1",
                is_deprecated=False,
                has_code_example=False,
                chunk_type="api_signature",
                text="RecognizeImage signature",
                tokens=40,
                checksum="chunk-apiref-1",
                executable_snippets=(),
            ),
        )

    app.state.source_hugo_normalization_orchestrator.get_latest_chunk_records = (  # type: ignore[method-assign]
        _patched_get_latest_chunk_records
    )

    with TestClient(app) as client:
        response = client.get(
            "/v1/integrations/triage",
            params={"product_id": "aspose.ocr", "stale_after_days": 30},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_items"] >= 3
    signals = {item["signal_type"] for item in payload["items"]}
    assert "no_active_snapshot" in signals
    assert "no_index_data" in signals
    assert "stale_snapshot" in signals
    assert "no_snippet_coverage" in signals
