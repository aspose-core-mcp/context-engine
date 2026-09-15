"""Tests for the tenant-aware lane adapter.

Asserts that the wrapper:
* short-circuits on zero/negative limit (matches inner contract);
* drops candidates whose tenant_id does not match the principal's;
* over-fetches from the inner adapter to compensate for the drop;
* respects the default-tenant-is-not-wildcard rule of the identity layer;
* surfaces structural errors on construction.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from adcs.admin.tenancy import DEFAULT_TENANT_ID
from adcs.retrieval.models import (
    FilterDebugMetadata,
    QueryPlan,
    QueryPlanDebugMetadata,
    ResolvedRetrievalFilters,
    RetrievalFilterRoute,
)
from adcs.retrieval.retrieval_models import (
    LaneCandidate,
    RetrievalCandidateMetadata,
)
from adcs.retrieval.tenant_lane_adapter import (
    TenantAwareLaneAdapter,
    matches_tenant_scope,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_plan() -> QueryPlan:
    filters = ResolvedRetrievalFilters(
        product_id="aspose.ocr",
        programming_language="net",
        preferred_version=None,
        strict_version=False,
        strict_version_value=None,
        locale_routing_order=("en",),
        routes=(
            RetrievalFilterRoute(
                product_id="aspose.ocr",
                programming_language="net",
                version=None,
                doc_locale="en",
            ),
        ),
        debug=FilterDebugMetadata(
            requested_product_id=None,
            requested_programming_language=None,
            requested_version=None,
            requested_doc_locale=None,
            effective_product_id="aspose.ocr",
            effective_programming_language="net",
            preferred_version=None,
            strict_version_value=None,
            strict_version_enforced=False,
            locale_routing_order=("en",),
            locale_fallback_to_en_enabled=True,
        ),
    )
    debug = QueryPlanDebugMetadata(
        raw_query="x",
        normalized_query="x",
        removed_noise_prefixes=(),
        symbol_candidates=(),
        intent="general_reference",
        intent_subtype=None,
        intent_reason_codes=(),
        detected_version_tokens=(),
        prefers_latest_stable=False,
        filter_debug=filters.debug,
    )
    return QueryPlan(
        normalized_query="x",
        query_fingerprint="fp",
        symbol_candidates=(),
        intent="general_reference",
        intent_subtype=None,
        intent_reason_codes=(),
        detected_version_tokens=(),
        prefers_latest_stable=False,
        filters=filters,
        debug=debug,
    )


def _make_candidate(*, idx: int, tenant_id: str = "default") -> LaneCandidate:
    meta = RetrievalCandidateMetadata(
        candidate_id=f"cand-{idx}",
        chunk_id=f"chunk-{idx}",
        snapshot_id="snap-1",
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        doc_type="how_to",
        doc_locale="en",
        symbol_fqn=None,
        title=f"Doc {idx}",
        canonical_url=f"https://example.com/{idx}",
        section_anchor=f"sec-{idx}",
        source_revision=f"rev-{idx}",
        repo_id="aspose.ocr.docs",
        text="body",
        checksum=f"chk-{idx}",
        tenant_id=tenant_id,
    )
    return LaneCandidate(metadata=meta, raw_score=1.0 - idx * 0.01)


class _FakeLaneAdapter:
    """Returns a fixed list of candidates, recording the limit it was asked for."""

    def __init__(self, candidates: Sequence[LaneCandidate]) -> None:
        self._candidates = tuple(candidates)
        self.last_limit_requested: int | None = None

    def search(
        self, *, plan: QueryPlan, limit: int
    ) -> tuple[LaneCandidate, ...]:
        self.last_limit_requested = limit
        return self._candidates[:limit]


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_construction_rejects_empty_tenant_id() -> None:
    fake = _FakeLaneAdapter(())
    with pytest.raises(ValueError, match="non-empty"):
        TenantAwareLaneAdapter(inner=fake, tenant_id="")


def test_construction_rejects_zero_over_fetch_factor() -> None:
    fake = _FakeLaneAdapter(())
    with pytest.raises(ValueError, match="must be >= 1"):
        TenantAwareLaneAdapter(inner=fake, tenant_id="t-acme", over_fetch_factor=0)


# ---------------------------------------------------------------------------
# Limit semantics
# ---------------------------------------------------------------------------


def test_zero_limit_returns_empty_without_calling_inner() -> None:
    fake = _FakeLaneAdapter([_make_candidate(idx=0)])
    wrapper = TenantAwareLaneAdapter(inner=fake, tenant_id="default")
    out = wrapper.search(plan=_make_plan(), limit=0)
    assert out == ()
    assert fake.last_limit_requested is None


def test_negative_limit_returns_empty_without_calling_inner() -> None:
    fake = _FakeLaneAdapter([_make_candidate(idx=0)])
    wrapper = TenantAwareLaneAdapter(inner=fake, tenant_id="default")
    out = wrapper.search(plan=_make_plan(), limit=-5)
    assert out == ()
    assert fake.last_limit_requested is None


def test_inner_adapter_is_over_fetched_by_factor() -> None:
    """The wrapper requests limit * over_fetch_factor from the inner adapter."""
    fake = _FakeLaneAdapter(
        [_make_candidate(idx=i) for i in range(50)]
    )
    wrapper = TenantAwareLaneAdapter(
        inner=fake, tenant_id="default", over_fetch_factor=4
    )
    wrapper.search(plan=_make_plan(), limit=5)
    assert fake.last_limit_requested == 20


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_named_tenant_sees_only_its_own_candidates() -> None:
    fake = _FakeLaneAdapter(
        [
            _make_candidate(idx=0, tenant_id="t-acme"),
            _make_candidate(idx=1, tenant_id="t-beta"),
            _make_candidate(idx=2, tenant_id="t-acme"),
            _make_candidate(idx=3, tenant_id="t-beta"),
        ]
    )
    wrapper = TenantAwareLaneAdapter(inner=fake, tenant_id="t-acme")
    out = wrapper.search(plan=_make_plan(), limit=10)
    assert {c.metadata.candidate_id for c in out} == {"cand-0", "cand-2"}


def test_default_tenant_sees_only_default_tenant_candidates() -> None:
    """Default tenant is NOT a wildcard — must not see named-tenant chunks."""
    fake = _FakeLaneAdapter(
        [
            _make_candidate(idx=0, tenant_id="default"),
            _make_candidate(idx=1, tenant_id="t-acme"),
            _make_candidate(idx=2, tenant_id="default"),
        ]
    )
    wrapper = TenantAwareLaneAdapter(inner=fake, tenant_id="default")
    out = wrapper.search(plan=_make_plan(), limit=10)
    assert {c.metadata.candidate_id for c in out} == {"cand-0", "cand-2"}


def test_named_tenant_cannot_see_default_tenant_candidates() -> None:
    """Named tenant cannot leak into the legacy default-tenant pool."""
    fake = _FakeLaneAdapter(
        [
            _make_candidate(idx=0, tenant_id="default"),
            _make_candidate(idx=1, tenant_id="t-acme"),
        ]
    )
    wrapper = TenantAwareLaneAdapter(inner=fake, tenant_id="t-acme")
    out = wrapper.search(plan=_make_plan(), limit=10)
    assert {c.metadata.candidate_id for c in out} == {"cand-1"}


def test_filter_preserves_inner_ranking_order() -> None:
    """The wrapper must not reorder the candidates it keeps."""
    fake = _FakeLaneAdapter(
        [
            _make_candidate(idx=0, tenant_id="t-acme"),
            _make_candidate(idx=1, tenant_id="t-other"),
            _make_candidate(idx=2, tenant_id="t-acme"),
            _make_candidate(idx=3, tenant_id="t-acme"),
        ]
    )
    wrapper = TenantAwareLaneAdapter(inner=fake, tenant_id="t-acme")
    out = wrapper.search(plan=_make_plan(), limit=10)
    assert [c.metadata.candidate_id for c in out] == [
        "cand-0",
        "cand-2",
        "cand-3",
    ]


def test_limit_caps_output_after_filtering() -> None:
    """If post-filtered results exceed limit, the wrapper trims to limit."""
    fake = _FakeLaneAdapter(
        [_make_candidate(idx=i, tenant_id="t-acme") for i in range(20)]
    )
    wrapper = TenantAwareLaneAdapter(
        inner=fake, tenant_id="t-acme", over_fetch_factor=5
    )
    out = wrapper.search(plan=_make_plan(), limit=3)
    assert len(out) == 3


# ---------------------------------------------------------------------------
# matches_tenant_scope helper
# ---------------------------------------------------------------------------


def test_matches_tenant_scope_same_tenant() -> None:
    candidate = _make_candidate(idx=0, tenant_id="t-acme")
    assert matches_tenant_scope(candidate=candidate, principal_tenant_id="t-acme")


def test_matches_tenant_scope_cross_named_denied() -> None:
    candidate = _make_candidate(idx=0, tenant_id="t-acme")
    assert not matches_tenant_scope(
        candidate=candidate, principal_tenant_id="t-beta"
    )


def test_matches_tenant_scope_default_to_default() -> None:
    candidate = _make_candidate(idx=0, tenant_id=DEFAULT_TENANT_ID)
    assert matches_tenant_scope(
        candidate=candidate, principal_tenant_id=DEFAULT_TENANT_ID
    )


def test_matches_tenant_scope_default_does_not_grant_wildcard() -> None:
    """A default-tenant candidate is invisible to a named-tenant principal."""
    candidate = _make_candidate(idx=0, tenant_id=DEFAULT_TENANT_ID)
    assert not matches_tenant_scope(
        candidate=candidate, principal_tenant_id="t-acme"
    )


def test_default_tenant_id_on_candidate_metadata_when_omitted() -> None:
    """RetrievalCandidateMetadata.tenant_id defaults to the constant 'default'."""
    candidate = _make_candidate(idx=0)
    assert candidate.metadata.tenant_id == DEFAULT_TENANT_ID
