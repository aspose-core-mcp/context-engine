"""Versioned config history artifacts and in-memory index for rollback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ConfigHistoryRecord:
    change_id: str
    product_id: str
    config_scope: str
    config_key: str
    action_type: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    actor_key_id: str
    request_id: str | None
    reason: str | None
    rollback_of_change_id: str | None
    created_at: datetime
    artifact_path: str


class InMemoryConfigHistoryService:
    """Persist config change artifacts and expose rollback lookup primitives."""

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        self._lock = Lock()
        self._workspace_root = workspace_root or Path(__file__).resolve().parents[3]
        self._artifact_root = (self._workspace_root / "artifacts" / "config-history").resolve()
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, ConfigHistoryRecord] = {}
        self._order: list[str] = []

    def record_change(
        self,
        *,
        product_id: str,
        config_scope: str,
        config_key: str,
        action_type: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        actor_key_id: str,
        request_id: str | None,
        reason: str | None = None,
        rollback_of_change_id: str | None = None,
    ) -> ConfigHistoryRecord:
        normalized_product_id = product_id.strip().casefold()
        normalized_scope = config_scope.strip()
        normalized_key = config_key.strip()
        normalized_action_type = action_type.strip()
        normalized_actor_key_id = actor_key_id.strip()
        if not normalized_product_id:
            msg = "product_id must not be empty."
            raise ValueError(msg)
        if not normalized_scope:
            msg = "config_scope must not be empty."
            raise ValueError(msg)
        if not normalized_key:
            msg = "config_key must not be empty."
            raise ValueError(msg)
        if not normalized_action_type:
            msg = "action_type must not be empty."
            raise ValueError(msg)
        if not normalized_actor_key_id:
            msg = "actor_key_id must not be empty."
            raise ValueError(msg)

        created_at = datetime.now(tz=UTC)
        change_id = str(uuid4())
        timestamp = created_at.strftime("%Y%m%d-%H%M%S")
        product_dir = self._artifact_root / normalized_product_id
        product_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = product_dir / f"{timestamp}-{change_id}.json"

        record = ConfigHistoryRecord(
            change_id=change_id,
            product_id=normalized_product_id,
            config_scope=normalized_scope,
            config_key=normalized_key,
            action_type=normalized_action_type,
            before=before,
            after=after,
            actor_key_id=normalized_actor_key_id,
            request_id=request_id,
            reason=reason,
            rollback_of_change_id=rollback_of_change_id,
            created_at=created_at,
            artifact_path=str(artifact_path),
        )

        artifact_payload = {
            "change_id": record.change_id,
            "product_id": record.product_id,
            "config_scope": record.config_scope,
            "config_key": record.config_key,
            "action_type": record.action_type,
            "before": record.before,
            "after": record.after,
            "actor_key_id": record.actor_key_id,
            "request_id": record.request_id,
            "reason": record.reason,
            "rollback_of_change_id": record.rollback_of_change_id,
            "created_at": record.created_at.isoformat(),
            "artifact_path": record.artifact_path,
        }
        artifact_path.write_text(
            json.dumps(artifact_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self._lock:
            self._records[record.change_id] = record
            self._order.append(record.change_id)
        return record

    def list_changes(
        self,
        *,
        limit: int = 50,
        product_id: str | None = None,
        config_scope: str | None = None,
    ) -> tuple[ConfigHistoryRecord, ...]:
        if limit < 1:
            return ()
        with self._lock:
            ordered = [self._records[change_id] for change_id in reversed(self._order)]

        if product_id is not None:
            normalized_product_id = product_id.strip().casefold()
            ordered = [item for item in ordered if item.product_id == normalized_product_id]
        if config_scope is not None:
            normalized_scope = config_scope.strip().casefold()
            ordered = [item for item in ordered if item.config_scope.casefold() == normalized_scope]
        return tuple(ordered[:limit])

    def get_change(self, change_id: str) -> ConfigHistoryRecord | None:
        with self._lock:
            return self._records.get(change_id)
