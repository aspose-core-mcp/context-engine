from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from adcs.ingestion.job_repository import (
    IngestionIdempotencyConflictError,
    InMemoryIngestionJobRepository,
)


def test_in_memory_ingestion_job_repository_upserts_and_lists_latest_first() -> None:
    repository = InMemoryIngestionJobRepository()
    started_at = datetime(2026, 2, 26, 12, 0, tzinfo=UTC)
    finished_at = datetime(2026, 2, 26, 12, 1, tzinfo=UTC)

    repository.upsert(
        operation_id="job-1",
        status="queued",
        repo_ids=("aspose.ocr.docs",),
        mode="publish",
        partial_publish_threshold_pct=30,
        request_id="req-1",
        started_at=None,
        finished_at=None,
        error_message=None,
    )
    repository.upsert(
        operation_id="job-2",
        status="running",
        repo_ids=("aspose.ocr.apiref",),
        mode="publish",
        partial_publish_threshold_pct=30,
        request_id="req-2",
        started_at=started_at,
        finished_at=None,
        error_message=None,
    )
    repository.upsert(
        operation_id="job-2",
        status="completed",
        repo_ids=("aspose.ocr.apiref",),
        mode="publish",
        partial_publish_threshold_pct=30,
        request_id="req-2",
        started_at=started_at,
        finished_at=finished_at,
        error_message=None,
    )

    listed = repository.list(limit=10)
    assert [record.operation_id for record in listed] == ["job-2", "job-1"]
    assert listed[0].status == "completed"
    assert listed[0].finished_at == finished_at

    loaded = repository.get("job-1")
    assert loaded is not None
    assert loaded.repo_ids == ("aspose.ocr.docs",)
    assert loaded.mode == "publish"


def test_in_memory_ingestion_job_repository_claims_idempotency_without_duplicates() -> None:
    repository = InMemoryIngestionJobRepository()
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=5)

    first_claim = repository.claim_idempotency(
        idempotency_key="idem-1",
        idempotency_scope="scope-1",
        operation_id="job-1",
        request_fingerprint="fp-1",
        expires_at=expires_at,
    )
    assert first_claim.operation_id == "job-1"
    assert first_claim.reused is False

    second_claim = repository.claim_idempotency(
        idempotency_key="idem-1",
        idempotency_scope="scope-1",
        operation_id="job-2",
        request_fingerprint="fp-1",
        expires_at=expires_at + timedelta(minutes=1),
    )
    assert second_claim.operation_id == "job-1"
    assert second_claim.reused is True


def test_in_memory_ingestion_job_repository_rejects_conflicting_idempotency_payload() -> None:
    repository = InMemoryIngestionJobRepository()
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=5)

    repository.claim_idempotency(
        idempotency_key="idem-2",
        idempotency_scope="scope-2",
        operation_id="job-10",
        request_fingerprint="fp-original",
        expires_at=expires_at,
    )

    with pytest.raises(IngestionIdempotencyConflictError):
        repository.claim_idempotency(
            idempotency_key="idem-2",
            idempotency_scope="scope-2",
            operation_id="job-11",
            request_fingerprint="fp-different",
            expires_at=expires_at + timedelta(minutes=1),
        )


def test_in_memory_ingestion_job_repository_persists_retry_and_cancel_metadata() -> None:
    repository = InMemoryIngestionJobRepository()
    now = datetime.now(tz=UTC)

    record = repository.upsert(
        operation_id="job-retry-1",
        status="retry_scheduled",
        repo_ids=("aspose.ocr.docs",),
        mode="publish",
        partial_publish_threshold_pct=30,
        request_id="req-retry-1",
        started_at=now,
        finished_at=now,
        error_message="transient failure",
        attempt_count=2,
        max_attempts=5,
        next_retry_at=now + timedelta(seconds=10),
        last_error_kind="transient_error",
        cancel_requested_at=None,
        cancelled_at=None,
        resumable=True,
    )

    assert record.attempt_count == 2
    assert record.max_attempts == 5
    assert record.next_retry_at is not None
    assert record.last_error_kind == "transient_error"
    assert record.resumable is True

    cancelled = repository.upsert(
        operation_id="job-retry-1",
        status="cancelled",
        repo_ids=("aspose.ocr.docs",),
        mode="publish",
        partial_publish_threshold_pct=30,
        request_id="req-retry-1",
        started_at=now,
        finished_at=now,
        error_message="cancelled",
        attempt_count=2,
        max_attempts=5,
        cancelled_at=now,
        resumable=True,
    )
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None
