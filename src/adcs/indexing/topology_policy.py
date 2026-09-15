"""Config-driven index topology policy for Qdrant/OpenSearch lanes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class QdrantTopologyPolicy:
    """Resolved Qdrant topology knobs."""

    shard_number: int = 1
    replication_factor: int = 1
    write_consistency_factor: int = 1


@dataclass(frozen=True, slots=True)
class OpenSearchTopologyPolicy:
    """Resolved OpenSearch topology knobs."""

    number_of_shards: int = 1
    number_of_replicas: int = 0
    refresh_interval: str = "1s"


@dataclass(frozen=True, slots=True)
class CompactionTopologyPolicy:
    """Resolved snapshot compaction and retention policy."""

    enabled: bool = False
    max_inactive_snapshots_per_scope: int = 3
    stale_snapshot_retention_days: int = 30


@dataclass(frozen=True, slots=True)
class StorageTieringPolicy:
    """Resolved storage tiering labels."""

    latest_stable_tier: str = "hot"
    archive_tier: str = "warm"


@dataclass(frozen=True, slots=True)
class IndexTopologyPolicy:
    """Resolved data-plane topology profile for the current environment."""

    profile: str
    qdrant: QdrantTopologyPolicy
    opensearch: OpenSearchTopologyPolicy
    compaction: CompactionTopologyPolicy
    storage_tiering: StorageTieringPolicy


def load_index_topology_policy(
    *,
    profile: str,
    config_path: str | Path,
) -> IndexTopologyPolicy:
    """Load index topology policy from JSON config."""

    path = Path(config_path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = "Index topology policy must be a JSON object."
        raise ValueError(msg)

    profiles_payload = payload.get("profiles")
    if not isinstance(profiles_payload, dict):
        msg = "Index topology policy requires `profiles` object."
        raise ValueError(msg)

    profile_key = profile.strip().casefold()
    resolved_payload = profiles_payload.get(profile_key)
    if not isinstance(resolved_payload, dict):
        available = sorted(str(key) for key in profiles_payload)
        msg = (
            "Index topology policy profile is not configured: "
            f"{profile_key!r}. Available profiles: {available}"
        )
        raise ValueError(msg)

    return IndexTopologyPolicy(
        profile=profile_key,
        qdrant=_parse_qdrant_policy(resolved_payload.get("qdrant")),
        opensearch=_parse_opensearch_policy(resolved_payload.get("opensearch")),
        compaction=_parse_compaction_policy(resolved_payload.get("compaction")),
        storage_tiering=_parse_storage_tiering_policy(
            resolved_payload.get("storage_tiering")
        ),
    )


def _parse_qdrant_policy(raw_payload: object) -> QdrantTopologyPolicy:
    payload = _ensure_mapping(raw_payload, section="qdrant")
    return QdrantTopologyPolicy(
        shard_number=_positive_int(payload.get("shard_number"), default=1),
        replication_factor=_positive_int(payload.get("replication_factor"), default=1),
        write_consistency_factor=_positive_int(
            payload.get("write_consistency_factor"),
            default=1,
        ),
    )


def _parse_opensearch_policy(raw_payload: object) -> OpenSearchTopologyPolicy:
    payload = _ensure_mapping(raw_payload, section="opensearch")
    refresh_interval = str(payload.get("refresh_interval", "1s")).strip() or "1s"
    return OpenSearchTopologyPolicy(
        number_of_shards=_positive_int(payload.get("number_of_shards"), default=1),
        number_of_replicas=_non_negative_int(
            payload.get("number_of_replicas"),
            default=0,
        ),
        refresh_interval=refresh_interval,
    )


def _parse_compaction_policy(raw_payload: object) -> CompactionTopologyPolicy:
    payload = _ensure_mapping(raw_payload, section="compaction")
    return CompactionTopologyPolicy(
        enabled=bool(payload.get("enabled", False)),
        max_inactive_snapshots_per_scope=_positive_int(
            payload.get("max_inactive_snapshots_per_scope"),
            default=3,
        ),
        stale_snapshot_retention_days=_positive_int(
            payload.get("stale_snapshot_retention_days"),
            default=30,
        ),
    )


def _parse_storage_tiering_policy(raw_payload: object) -> StorageTieringPolicy:
    payload = _ensure_mapping(raw_payload, section="storage_tiering")
    latest_stable_tier = str(payload.get("latest_stable_tier", "hot")).strip() or "hot"
    archive_tier = str(payload.get("archive_tier", "warm")).strip() or "warm"
    return StorageTieringPolicy(
        latest_stable_tier=latest_stable_tier,
        archive_tier=archive_tier,
    )


def _ensure_mapping(raw_payload: object, *, section: str) -> dict[str, Any]:
    if raw_payload is None:
        return {}
    if not isinstance(raw_payload, dict):
        msg = f"Index topology policy section `{section}` must be an object."
        raise ValueError(msg)
    return raw_payload


def _positive_int(raw_value: object, *, default: int) -> int:
    if raw_value is None:
        return default
    value = _coerce_int(raw_value)
    if value < 1:
        msg = f"Expected positive integer, got {raw_value!r}."
        raise ValueError(msg)
    return value


def _non_negative_int(raw_value: object, *, default: int) -> int:
    if raw_value is None:
        return default
    value = _coerce_int(raw_value)
    if value < 0:
        msg = f"Expected non-negative integer, got {raw_value!r}."
        raise ValueError(msg)
    return value


def _coerce_int(raw_value: object) -> int:
    if isinstance(raw_value, bool):
        msg = f"Boolean value is not a valid integer: {raw_value!r}."
        raise ValueError(msg)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        if raw_value.is_integer():
            return int(raw_value)
        msg = f"Float value must be integral: {raw_value!r}."
        raise ValueError(msg)
    if isinstance(raw_value, str):
        normalized = raw_value.strip()
        if not normalized:
            msg = "String value must not be empty."
            raise ValueError(msg)
        return int(normalized)
    msg = f"Unsupported integer value: {raw_value!r}."
    raise ValueError(msg)
