"""WebMCP write-invocation audit trail contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any


class WebMCPWriteAuditStatus(StrEnum):
    """Outcome status for one WebMCP write invocation."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FORBIDDEN = "forbidden"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WebMCPWriteAuditRecord:
    """One auditable WebMCP write invocation."""

    audit_id: str
    tool_name: str
    status: WebMCPWriteAuditStatus
    actor_key_id: str
    request_id: str | None
    reason: str | None
    confirm_token_hash: str | None
    target: dict[str, Any]
    error_code: str | None
    created_at: datetime


class InMemoryWebMCPWriteAuditStore:
    """In-memory audit trail for WebMCP write invocations."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = 0
        self._records: list[WebMCPWriteAuditRecord] = []

    def record(
        self,
        *,
        tool_name: str,
        status: WebMCPWriteAuditStatus,
        actor_key_id: str,
        request_id: str | None,
        reason: str | None,
        confirm_token: str | None,
        target: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> WebMCPWriteAuditRecord:
        with self._lock:
            self._counter += 1
            record = WebMCPWriteAuditRecord(
                audit_id=f"wmcp-audit-{self._counter:08d}",
                tool_name=tool_name.strip(),
                status=status,
                actor_key_id=actor_key_id.strip(),
                request_id=request_id.strip() if isinstance(request_id, str) else None,
                reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
                confirm_token_hash=_hash_confirm_token(confirm_token),
                target=dict(target or {}),
                error_code=(
                    error_code.strip()
                    if isinstance(error_code, str) and error_code.strip()
                    else None
                ),
                created_at=datetime.now(tz=UTC),
            )
            self._records.append(record)
            return record

    def list_records(
        self,
        *,
        limit: int = 100,
        tool_name: str | None = None,
        status: WebMCPWriteAuditStatus | None = None,
    ) -> tuple[WebMCPWriteAuditRecord, ...]:
        if limit < 1:
            return ()
        normalized_tool = tool_name.strip() if isinstance(tool_name, str) else None
        with self._lock:
            records = tuple(self._records)
        filtered = tuple(
            item
            for item in records
            if (normalized_tool is None or item.tool_name == normalized_tool)
            and (status is None or item.status is status)
        )
        return tuple(reversed(filtered[-limit:]))


def _hash_confirm_token(confirm_token: str | None) -> str | None:
    if confirm_token is None:
        return None
    normalized = confirm_token.strip()
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:16]
