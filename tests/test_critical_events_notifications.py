from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
    SourceHugoNormalizationStatus,
)
from adcs.ops import (
    CriticalEventSeverity,
    CriticalEventType,
    InMemoryCriticalEventStore,
    InMemorySmtpTransport,
    NotificationService,
    NotificationStatus,
)


def _write_registry(tmp_path: Path, payload: dict[str, Any]) -> Path:
    registry_path = tmp_path / "config" / "source-repositories.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    return registry_path


def _make_registry_payload() -> dict[str, Any]:
    return {
        "source_roots": [
            {"root_id": "docs-root", "source_kind": "docs", "path": "source-repo-docs"},
        ],
        "repositories": [
            {
                "repo_id": "aspose.ocr.docs",
                "product_id": "aspose.ocr",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OCR",
                "source_kind": "docs",
                "git": {
                    "url": "https://example.com/aspose.ocr.docs.git",
                    "submodule_path": "source-repo-docs/Aspose.OCR",
                    "default_branch": "main",
                },
                "layout_detection": {
                    "layout_type": "doc_locale/programming_language/content",
                },
            }
        ],
    }


def test_critical_event_store_and_notification_service_are_deterministic() -> None:
    event_store = InMemoryCriticalEventStore()
    smtp_transport = InMemorySmtpTransport()
    notification_service = NotificationService(smtp_transport=smtp_transport)

    event = event_store.emit(
        severity=CriticalEventSeverity.HIGH,
        event_type=CriticalEventType.PARTIAL_PUBLISH,
        message="Partial publish accepted.",
        details={"repo_id": "aspose.ocr.docs"},
    )
    dispatch = notification_service.notify_event(event)

    assert event.event_id == "evt-00000001"
    assert event.event_type is CriticalEventType.PARTIAL_PUBLISH
    assert dispatch.notification_id == "smtp-00000001"
    assert dispatch.status is NotificationStatus.SENT
    assert dispatch.event_id == event.event_id
    assert smtp_transport.list_messages(limit=1)[0].subject.endswith("partial_publish")


def test_orchestrator_emits_critical_fail_event_and_smtp_notification_on_failure(
    tmp_path: Path,
) -> None:
    # A genuinely invalid registry (a deploy/config failure) must still raise a
    # CRITICAL event + notification. An unregistered repo_id, by contrast, is now
    # skipped gracefully (see test_orchestrator_skips_unregistered_repo_*).
    (tmp_path / "source-repo-docs" / "Aspose.OCR").mkdir(parents=True, exist_ok=True)
    corrupt_payload = _make_registry_payload()
    corrupt_payload["source_roots"] = []  # invalid → SourceRegistryValidationError
    registry_path = _write_registry(tmp_path, corrupt_payload)
    event_store = InMemoryCriticalEventStore()
    smtp_transport = InMemorySmtpTransport()
    notification_service = NotificationService(smtp_transport=smtp_transport)
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        critical_event_publisher=event_store,
        notification_service=notification_service,
    )

    operation = service.run(repo_ids=("aspose.ocr.docs",))

    assert operation.status is SourceHugoNormalizationStatus.FAILED
    assert operation.results == ()
    assert any("[critical_event]" in line.line for line in operation.logs)
    assert any("[notification]" in line.line for line in operation.logs)

    events = event_store.list_events(limit=1)
    assert len(events) == 1
    assert events[0].event_type is CriticalEventType.INGESTION_CRITICAL_FAIL
    assert events[0].severity is CriticalEventSeverity.CRITICAL

    dispatches = notification_service.list_dispatches(limit=1)
    assert len(dispatches) == 1
    assert dispatches[0].status is NotificationStatus.SENT
    assert dispatches[0].event_id == events[0].event_id


def test_orchestrator_skips_unregistered_repo_without_critical(
    tmp_path: Path,
) -> None:
    # Resilience: an unregistered/mistyped repo_id is skipped (logged) — the run
    # still COMPLETES and NO critical event/notification is emitted. Ingestion
    # must never crash on a repo it simply doesn't know about.
    (tmp_path / "source-repo-docs" / "Aspose.OCR").mkdir(parents=True, exist_ok=True)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    event_store = InMemoryCriticalEventStore()
    smtp_transport = InMemorySmtpTransport()
    notification_service = NotificationService(smtp_transport=smtp_transport)
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        critical_event_publisher=event_store,
        notification_service=notification_service,
    )

    operation = service.run(repo_ids=("missing.repo",))

    assert operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert any(
        "[skipped]" in line.line and "missing.repo" in line.line
        for line in operation.logs
    )
    assert len(event_store.list_events(limit=5)) == 0
    assert len(notification_service.list_dispatches(limit=5)) == 0


def test_orchestrator_isolates_unexpected_repo_error(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # Resilience under ANY condition: even an UNEXPECTED error type (not a known
    # parse/validation error) in one repo must be isolated — the run completes
    # rather than crashing with an unhandled exception.
    (tmp_path / "source-repo-docs" / "Aspose.OCR").mkdir(parents=True, exist_ok=True)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
    )

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("unexpected boom in normalize")

    monkeypatch.setattr(service, "_normalize_repository", _boom)

    operation = service.run(repo_ids=("aspose.ocr.docs",))

    assert operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert any(
        "[skipped]" in line.line and "aspose.ocr.docs" in line.line
        for line in operation.logs
    )
