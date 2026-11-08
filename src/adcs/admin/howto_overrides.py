"""File-backed How-To draft/published override workflow."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class LocalizedTextRecord:
    en: str = ""
    ru: str = ""


@dataclass(frozen=True, slots=True)
class LocalizedLinesRecord:
    en: tuple[str, ...] = ()
    ru: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HowToCalloutRecord:
    id: str
    level: str
    title: LocalizedTextRecord
    body: LocalizedLinesRecord


@dataclass(frozen=True, slots=True)
class HowToCommandRecord:
    id: str
    label: LocalizedTextRecord
    description: LocalizedTextRecord
    command: str


@dataclass(frozen=True, slots=True)
class HowToScreenshotRecord:
    id: str
    src: str
    alt: LocalizedTextRecord
    caption: LocalizedTextRecord


@dataclass(frozen=True, slots=True)
class HowToExampleRecord:
    id: str
    title: LocalizedTextRecord
    bullets: LocalizedLinesRecord


@dataclass(frozen=True, slots=True)
class HowToOverridePayloadRecord:
    entry_label: LocalizedTextRecord = field(default_factory=LocalizedTextRecord)
    title: LocalizedTextRecord = field(default_factory=LocalizedTextRecord)
    summary: LocalizedTextRecord = field(default_factory=LocalizedTextRecord)
    purpose: LocalizedLinesRecord = field(default_factory=LocalizedLinesRecord)
    workflow: LocalizedLinesRecord = field(default_factory=LocalizedLinesRecord)
    callouts: tuple[HowToCalloutRecord, ...] = ()
    commands: tuple[HowToCommandRecord, ...] = ()
    examples: tuple[HowToExampleRecord, ...] = ()
    screenshots: tuple[HowToScreenshotRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class HowToOverrideEnvelope:
    article_id: str
    draft: HowToOverridePayloadRecord | None
    draft_updated_at: datetime | None
    draft_updated_by: str | None
    published: HowToOverridePayloadRecord | None
    published_updated_at: datetime | None
    published_updated_by: str | None


def _localized_text_from_payload(payload: dict[str, Any] | None) -> LocalizedTextRecord:
    payload = payload or {}
    return LocalizedTextRecord(
        en=str(payload.get("en") or "").strip(),
        ru=str(payload.get("ru") or "").strip(),
    )


def _localized_lines_from_payload(payload: dict[str, Any] | None) -> LocalizedLinesRecord:
    payload = payload or {}
    return LocalizedLinesRecord(
        en=tuple(str(item).strip() for item in payload.get("en") or [] if str(item).strip()),
        ru=tuple(str(item).strip() for item in payload.get("ru") or [] if str(item).strip()),
    )


def _payload_from_dict(payload: dict[str, Any] | None) -> HowToOverridePayloadRecord | None:
    if payload is None:
        return None
    return HowToOverridePayloadRecord(
        entry_label=_localized_text_from_payload(payload.get("entry_label")),
        title=_localized_text_from_payload(payload.get("title")),
        summary=_localized_text_from_payload(payload.get("summary")),
        purpose=_localized_lines_from_payload(payload.get("purpose")),
        workflow=_localized_lines_from_payload(payload.get("workflow")),
        callouts=tuple(
            HowToCalloutRecord(
                id=str(item.get("id") or f"callout-{index + 1}").strip(),
                level=str(item.get("level") or "info").strip() or "info",
                title=_localized_text_from_payload(item.get("title")),
                body=_localized_lines_from_payload(item.get("body")),
            )
            for index, item in enumerate(payload.get("callouts") or [])
            if isinstance(item, dict)
        ),
        commands=tuple(
            HowToCommandRecord(
                id=str(item.get("id") or f"command-{index + 1}").strip(),
                label=_localized_text_from_payload(item.get("label")),
                description=_localized_text_from_payload(item.get("description")),
                command=str(item.get("command") or "").strip(),
            )
            for index, item in enumerate(payload.get("commands") or [])
            if isinstance(item, dict)
        ),
        examples=tuple(
            HowToExampleRecord(
                id=str(item.get("id") or f"example-{index + 1}").strip(),
                title=_localized_text_from_payload(item.get("title")),
                bullets=_localized_lines_from_payload(item.get("bullets")),
            )
            for index, item in enumerate(payload.get("examples") or [])
            if isinstance(item, dict)
        ),
        screenshots=tuple(
            HowToScreenshotRecord(
                id=str(item.get("id") or f"screenshot-{index + 1}").strip(),
                src=str(item.get("src") or "").strip(),
                alt=_localized_text_from_payload(item.get("alt")),
                caption=_localized_text_from_payload(item.get("caption")),
            )
            for index, item in enumerate(payload.get("screenshots") or [])
            if isinstance(item, dict)
        ),
    )


def _payload_to_dict(payload: HowToOverridePayloadRecord | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return asdict(payload)


class FileBackedHowToOverrideStore:
    """Persist draft/published how-to overrides in a JSON file."""

    def __init__(self, storage_path: Path, asset_dir: Path) -> None:
        self._storage_path = storage_path
        self._asset_dir = asset_dir
        self._lock = RLock()
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._asset_dir.mkdir(parents=True, exist_ok=True)
        if not self._storage_path.exists():
            self._write_raw({"records": []})

    def ping(self) -> None:
        self._load_raw()

    def list_records(self) -> tuple[HowToOverrideEnvelope, ...]:
        with self._lock:
            payload = self._load_raw()
            return tuple(self._envelope_from_dict(item) for item in payload.get("records", []))

    def get_record(self, article_id: str) -> HowToOverrideEnvelope:
        with self._lock:
            payload = self._load_raw()
            for item in payload.get("records", []):
                if item.get("article_id") == article_id:
                    return self._envelope_from_dict(item)
            return HowToOverrideEnvelope(
                article_id=article_id,
                draft=None,
                draft_updated_at=None,
                draft_updated_by=None,
                published=None,
                published_updated_at=None,
                published_updated_by=None,
            )

    def list_published_overrides(self) -> dict[str, HowToOverridePayloadRecord]:
        with self._lock:
            payload = self._load_raw()
            result: dict[str, HowToOverridePayloadRecord] = {}
            for item in payload.get("records", []):
                article_id = str(item.get("article_id") or "").strip()
                published = _payload_from_dict(item.get("published"))
                if article_id and published is not None:
                    result[article_id] = published
            return result

    def upsert_draft(
        self,
        *,
        article_id: str,
        payload: dict[str, Any],
        actor_key_id: str,
    ) -> HowToOverrideEnvelope:
        with self._lock:
            raw = self._load_raw()
            now = datetime.now(tz=UTC)
            record = self._find_or_create_record(raw, article_id)
            record["draft"] = _payload_to_dict(_payload_from_dict(payload))
            record["draft_updated_at"] = now.isoformat()
            record["draft_updated_by"] = actor_key_id
            self._write_raw(raw)
            return self._envelope_from_dict(record)

    def publish(self, *, article_id: str, actor_key_id: str) -> HowToOverrideEnvelope:
        with self._lock:
            raw = self._load_raw()
            record = self._find_or_create_record(raw, article_id)
            draft_payload = _payload_from_dict(record.get("draft"))
            if draft_payload is None:
                msg = f"No draft override exists for article_id={article_id}."
                raise ValueError(msg)
            now = datetime.now(tz=UTC)
            record["published"] = _payload_to_dict(draft_payload)
            record["published_updated_at"] = now.isoformat()
            record["published_updated_by"] = actor_key_id
            self._write_raw(raw)
            return self._envelope_from_dict(record)

    def reset_draft(self, *, article_id: str) -> HowToOverrideEnvelope:
        with self._lock:
            raw = self._load_raw()
            record = self._find_or_create_record(raw, article_id)
            record["draft"] = None
            record["draft_updated_at"] = None
            record["draft_updated_by"] = None
            self._write_raw(raw)
            return self._envelope_from_dict(record)

    def clear_published(self, *, article_id: str) -> HowToOverrideEnvelope:
        with self._lock:
            raw = self._load_raw()
            record = self._find_or_create_record(raw, article_id)
            record["published"] = None
            record["published_updated_at"] = None
            record["published_updated_by"] = None
            self._write_raw(raw)
            return self._envelope_from_dict(record)

    def store_asset(
        self,
        *,
        filename: str,
        content_base64: str,
    ) -> str:
        with self._lock:
            safe_name = f"{uuid4().hex}-{Path(filename).name}"
            try:
                payload = base64.b64decode(content_base64, validate=True)
            except (ValueError, binascii.Error) as exc:
                msg = "Invalid base64 payload."
                raise ValueError(msg) from exc
            target = self._asset_dir / safe_name
            target.write_bytes(payload)
            return safe_name

    def resolve_asset_path(self, asset_name: str) -> Path:
        asset_root = self._asset_dir.resolve()
        target = (asset_root / asset_name).resolve()
        if asset_root not in target.parents:
            msg = "Asset path escapes storage directory."
            raise ValueError(msg)
        return target

    def _find_or_create_record(self, payload: dict[str, Any], article_id: str) -> dict[str, Any]:
        article_id = article_id.strip()
        records = payload.setdefault("records", [])
        for item in records:
            if item.get("article_id") == article_id:
                return item
        item = {
            "article_id": article_id,
            "draft": None,
            "draft_updated_at": None,
            "draft_updated_by": None,
            "published": None,
            "published_updated_at": None,
            "published_updated_by": None,
        }
        records.append(item)
        return item

    def _envelope_from_dict(self, payload: dict[str, Any]) -> HowToOverrideEnvelope:
        def _parse_dt(value: Any) -> datetime | None:
            if not value:
                return None
            return datetime.fromisoformat(str(value))

        return HowToOverrideEnvelope(
            article_id=str(payload.get("article_id") or "").strip(),
            draft=_payload_from_dict(payload.get("draft")),
            draft_updated_at=_parse_dt(payload.get("draft_updated_at")),
            draft_updated_by=(
                str(payload.get("draft_updated_by")).strip()
                if payload.get("draft_updated_by")
                else None
            ),
            published=_payload_from_dict(payload.get("published")),
            published_updated_at=_parse_dt(payload.get("published_updated_at")),
            published_updated_by=(
                str(payload.get("published_updated_by")).strip()
                if payload.get("published_updated_by")
                else None
            ),
        )

    def _load_raw(self) -> dict[str, Any]:
        if not self._storage_path.exists():
            return {"records": []}
        raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = "Invalid how-to override store payload."
            raise ValueError(msg)
        raw.setdefault("records", [])
        return raw

    def _write_raw(self, payload: dict[str, Any]) -> None:
        self._storage_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
