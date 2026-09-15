"""Integration tests for tenant isolation in the public query pipeline.

:class:`TenantAwareLaneAdapter` is wired into ``PublicQueryService`` so
every retrieval lane is tenant-scoped.
These tests drive the *wired* service (not the wrapper in isolation —
that is covered by ``test_tenant_lane_adapter.py``) with a shared lane
pool holding candidates for three tenants, and assert:

* each tenant's query returns only its own candidates (no cross-tenant
  leak) at the retrieval seam (``_run_retrieval``);
* the default tenant is not a wildcard — it sees only ``"default"``
  candidates, never a named tenant's;
* the full ``query_docs`` response never surfaces a foreign tenant's
  chunk, regardless of downstream confidence gating;
* omitting the tenant argument falls back to the default tenant scope,
  preserving existing single-tenant behaviour.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from adcs.api.public_docs_query import PublicQueryService, QueryDocsRequest
from adcs.retrieval import HybridScoringConfig, TranslationFallbackService
from adcs.retrieval.models import QueryPlan
from adcs.retrieval.retrieval_models import (
    LaneCandidate,
    RetrievalCandidateMetadata,
)

_ACME = "t-acme"
_BETA = "t-beta"
_DEFAULT = "default"

# chunk_id → tenant_id, the shared pool every lane returns.
_POOL = {
    "chunk-acme-1": _ACME,
    "chunk-acme-2": _ACME,
    "chunk-beta-1": _BETA,
    "chunk-beta-2": _BETA,
    "chunk-default-1": _DEFAULT,
}
_BY_TENANT: dict[str, set[str]] = {}
for _cid, _tid in _POOL.items():
    _BY_TENANT.setdefault(_tid, set()).add(_cid)


def _candidate(chunk_id: str, tenant_id: str, score: float) -> LaneCandidate:
    meta = RetrievalCandidateMetadata(
        candidate_id=chunk_id,
        chunk_id=chunk_id,
        snapshot_id=f"snap-{tenant_id}",
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        doc_type="how_to",
        doc_locale="en",
        symbol_fqn=None,
        title=f"Recognize text from image ({chunk_id})",
        canonical_url=f"https://docs.aspose.com/ocr/net/{chunk_id}",
        section_anchor="recognize",
        source_revision="rev-1",
        repo_id="aspose.ocr.docs",
        text="How to recognize text from an image with Aspose.OCR.",
        checksum=f"chk-{chunk_id}",
        tenant_id=tenant_id,
    )
    return LaneCandidate(metadata=meta, raw_score=score)


class _FakeLaneAdapter:
    """Returns the shared tenant-mixed pool, ignoring the plan."""

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        candidates = [
            _candidate(cid, tid, score=1.0 - i * 0.01)
            for i, (cid, tid) in enumerate(_POOL.items())
        ]
        return tuple(candidates[:limit])


def _service() -> PublicQueryService:
    translation = TranslationFallbackService.from_config_file(
        config_path=Path("config/translation_llm.json")
    )
    return PublicQueryService(
        # Not exercised: lane adapters are provided, so the orchestrator's
        # chunk-record fallback path is never taken.
        source_hugo_normalization_orchestrator=SimpleNamespace(),  # type: ignore[arg-type]
        translation_fallback_service=translation,
        dense_lane_adapter=_FakeLaneAdapter(),  # type: ignore[arg-type]
        lexical_lane_adapter=_FakeLaneAdapter(),  # type: ignore[arg-type]
        scoring_config=HybridScoringConfig(),
    )


def _plan(service: PublicQueryService) -> QueryPlan:
    # Reuse the service's own planner so the plan is realistic.
    from adcs.retrieval import QueryPlannerInput

    return service._query_planner.plan(
        request=QueryPlannerInput(
            query="recognize text from image",
            product_id="aspose.ocr",
            programming_language="net",
            version=None,
            doc_locale=None,
            strict_version=False,
        )
    )


# ---------------------------------------------------------------------------
# Retrieval-seam isolation (deterministic — no confidence gating)
# ---------------------------------------------------------------------------


def _retrieved_chunk_ids(service: PublicQueryService, tenant_id: str) -> set[str]:
    result = service._run_retrieval(
        plan=_plan(service),
        requested_doc_types=[],
        include_examples=True,
        tenant_id=tenant_id,
    )
    return {c.metadata.chunk_id for c in result.candidates}


def test_named_tenant_retrieves_only_its_own_candidates() -> None:
    service = _service()

    acme = _retrieved_chunk_ids(service, _ACME)
    beta = _retrieved_chunk_ids(service, _BETA)

    assert acme == _BY_TENANT[_ACME]
    assert beta == _BY_TENANT[_BETA]
    # No overlap — the two tenants' result sets are disjoint.
    assert acme.isdisjoint(beta)


def test_default_tenant_is_not_a_wildcard_at_retrieval() -> None:
    service = _service()

    default_ids = _retrieved_chunk_ids(service, _DEFAULT)

    assert default_ids == _BY_TENANT[_DEFAULT]
    # The default tenant must not see any named-tenant chunk.
    assert default_ids.isdisjoint(_BY_TENANT[_ACME])
    assert default_ids.isdisjoint(_BY_TENANT[_BETA])


def test_unknown_tenant_retrieves_nothing() -> None:
    service = _service()
    assert _retrieved_chunk_ids(service, "t-nonexistent") == set()


# ---------------------------------------------------------------------------
# Full query_docs response — no cross-tenant leak end to end
# ---------------------------------------------------------------------------


def _response_chunk_ids(
    service: PublicQueryService, tenant_id: str | None
) -> set[str]:
    request = QueryDocsRequest(
        query="recognize text from image",
        product_id="aspose.ocr",
        language="net",
        strict_version=False,
    )
    if tenant_id is None:
        response = service.query_docs(request=request)
    else:
        response = service.query_docs(request=request, tenant_id=tenant_id)
    return {item.chunk_id for item in response.results}


def test_query_docs_never_surfaces_foreign_tenant_chunks() -> None:
    service = _service()

    acme_ids = _response_chunk_ids(service, _ACME)
    beta_ids = _response_chunk_ids(service, _BETA)

    # Whatever survives downstream gating must belong to the queried tenant.
    assert acme_ids <= _BY_TENANT[_ACME]
    assert beta_ids <= _BY_TENANT[_BETA]
    # And must never include the other tenant's chunks.
    assert acme_ids.isdisjoint(_BY_TENANT[_BETA])
    assert beta_ids.isdisjoint(_BY_TENANT[_ACME])


def test_query_docs_default_scope_excludes_named_tenants() -> None:
    service = _service()

    default_ids = _response_chunk_ids(service, _DEFAULT)
    omitted_ids = _response_chunk_ids(service, None)  # no tenant kwarg

    # Omitting the tenant argument must behave exactly like the default tenant.
    assert default_ids == omitted_ids
    # Neither may surface a named tenant's chunk.
    assert default_ids <= _BY_TENANT[_DEFAULT]
    assert default_ids.isdisjoint(_BY_TENANT[_ACME])
    assert default_ids.isdisjoint(_BY_TENANT[_BETA])
