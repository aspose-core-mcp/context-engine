"""Byte-size-based pruning of heavy chunk payloads in persisted operation state.

Regression for the OOM fix: the prune trigger must be the estimated serialized
*byte size*, not a chunk count — so moderate operations stay fully reloadable
cross-process while only genuinely-huge (OOM-risk) operations are pruned.
"""

from __future__ import annotations

from adcs.ingestion.operation_state_store import (
    _MAX_PERSISTED_HEAVY_BYTES,
    _estimate_inline_chunk_bytes,
    _prune_heavy_results_for_persistence,
)


def _operation(*, chunk_count: int, text_kib: int) -> dict[str, object]:
    chunk = {
        "product_id": "aspose.slides",
        "programming_language": "net",
        "version": "25.1",
        "symbol_fqn": "A.B.C",
        "text": "x" * (text_kib * 1024),
    }
    return {
        "operation_id": "op",
        "results": [
            {
                "repo_id": "aspose.slides.apiref",
                "chunk_records": [dict(chunk) for _ in range(chunk_count)],
                "chunk_records_count": chunk_count,
                "canonical_documents": [],
                "pages": [],
                "staging_repository_manifest_path": "/staging/manifest.json",
            }
        ],
    }


def test_moderate_operation_is_not_pruned() -> None:
    # 30k small (~1 KiB) chunks => ~30 MB, well under the 200 MB cap and fully
    # reloadable via load() (which has no size cap) — must be kept verbatim.
    record = _operation(chunk_count=30_000, text_kib=1)
    assert _estimate_inline_chunk_bytes(record) < _MAX_PERSISTED_HEAVY_BYTES
    pruned = _prune_heavy_results_for_persistence(record, record_id="moderate")
    assert pruned is record  # untouched, same object
    assert len(pruned["results"][0]["chunk_records"]) == 30_000


def test_huge_operation_is_pruned_but_keeps_cardinality() -> None:
    # 5k fat (~75 KiB) chunks => ~375 MB, far above the cap and an OOM risk to
    # json.dumps — must be pruned, but cardinality + manifest path preserved.
    record = _operation(chunk_count=5_000, text_kib=75)
    assert _estimate_inline_chunk_bytes(record) > _MAX_PERSISTED_HEAVY_BYTES
    pruned = _prune_heavy_results_for_persistence(record, record_id="huge")
    assert pruned is not record  # a copy
    result = pruned["results"][0]
    assert result["chunk_records"] == []
    assert result["canonical_documents"] == []
    assert result["chunk_records_count"] == 5_000
    assert result["staging_repository_manifest_path"] == "/staging/manifest.json"
    assert result["_heavy_subfields_pruned"] is True
    # Original in-memory record must not be mutated.
    assert len(record["results"][0]["chunk_records"]) == 5_000
