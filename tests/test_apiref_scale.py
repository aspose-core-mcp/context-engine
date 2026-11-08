"""Scale/correctness check for the Postgres symbol store at volume.

Loads several thousand symbols across many scopes into live Postgres and
asserts that exact lookup, structural list, name search, and full-text all
return correct results with no cross-scope leakage — exercising the
text_pattern_ops / GIN fts / trigram indexes at a realistic size. Opt-in
(requires ADCS_TEST_POSTGRES_DSN); skipped in the default suite.
"""

from __future__ import annotations

import os
import time

import pytest

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    PostgresApiRefSymbolStore,
)
from adcs.retrieval.apiref_recall_eval import ApiRefEvalCase, evaluate_apiref_recall
from adcs.retrieval.two_source_retriever import ApiRefRetriever

_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")

_PRODUCTS = [f"scale.p{i}" for i in range(10)]  # 10 products
_CLASSES_PER_PRODUCT = 50
_METHODS_PER_CLASS = 10  # → 10 * 50 * (1 class + 10 methods) = 5500 symbols
SNAPSHOT = "scale-1"


def _corpus() -> dict[str, list[ApiRefSymbol]]:
    """Build ~5500 symbols grouped by product (one scope per product)."""
    by_product: dict[str, list[ApiRefSymbol]] = {}
    for product in _PRODUCTS:
        rows: list[ApiRefSymbol] = []
        for c in range(_CLASSES_PER_PRODUCT):
            class_fqn = f"{product}.Class{c}"
            rows.append(
                ApiRefSymbol(
                    snapshot_id=SNAPSHOT,
                    product=product,
                    language="net",
                    version="1",
                    locale="en",
                    kind="class",
                    member_fqn=class_fqn,
                    name=f"Class{c}",
                    parent_fqn=product,
                    signature=None,
                    canonical_url=f"https://ref/{class_fqn}",
                    is_deprecated=False,
                    summary=f"Class number {c} in {product} for widget processing.",
                    payload={},
                )
            )
            for m in range(_METHODS_PER_CLASS):
                method_fqn = f"{class_fqn}.Method{m}"
                rows.append(
                    ApiRefSymbol(
                        snapshot_id=SNAPSHOT,
                        product=product,
                        language="net",
                        version="1",
                        locale="en",
                        kind="method",
                        member_fqn=method_fqn,
                        name=f"Method{m}",
                        parent_fqn=class_fqn,
                        signature=f"void Method{m}(int arg{m})",
                        canonical_url=f"https://ref/{method_fqn}",
                        is_deprecated=False,
                        summary=f"Method {m} of class {c} that transforms input arg{m}.",
                        payload={},
                    )
                )
        by_product[product] = rows
    return by_product


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_postgres_symbol_store_at_scale() -> None:
    store = PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)  # type: ignore[arg-type]
    by_product = _corpus()
    total = sum(len(rows) for rows in by_product.values())
    assert total >= 5000

    # Bulk load + activate per product scope.
    for product, rows in by_product.items():
        for start in range(0, len(rows), 1000):
            store.upsert_symbols(rows[start : start + 1000])
        store.flip_active_snapshot(
            scope=ApiRefScope(product=product, language="net", version="1", locale="en"),
            snapshot_id=SNAPSHOT,
        )

    scope0 = ApiRefScope(product="scale.p0", language="net", version="1", locale="en")

    # Exact lookup at volume returns exactly the target.
    got = store.get_symbol(member_fqn="scale.p0.Class7.Method3", scope=scope0)
    assert len(got) == 1 and got[0].kind == "method"

    # Structural: a class has exactly its declared method children.
    members = store.list_members(parent_fqn="scale.p0.Class7", scope=scope0)
    assert len(members) == _METHODS_PER_CLASS
    assert all(m.parent_fqn == "scale.p0.Class7" for m in members)

    # Name search hits and never leaks across product scope.
    hits = store.search_symbols(pattern="Class7", scope=scope0, limit=50)
    assert hits
    assert all(h.member_fqn.startswith("scale.p0.") for h in hits)

    # Full-text over summaries works at volume.
    assert store.fts_search(query="transforms input", scope=scope0, limit=10)

    # Cross-scope isolation: a p0 symbol is invisible from p1's scope.
    scope1 = ApiRefScope(product="scale.p1", language="net", version="1", locale="en")
    assert store.get_symbol(member_fqn="scale.p0.Class7.Method3", scope=scope1) == ()

    # Recall stays perfect on a sample drawn from the large corpus.
    cases = [
        ApiRefEvalCase(f"scale.p0.Class{c}.Method0", f"scale.p0.Class{c}.Method0", "exact_fqn")
        for c in range(0, 40, 4)
    ] + [ApiRefEvalCase(f"Class{c}", f"scale.p0.Class{c}", "partial_name") for c in range(0, 9)]
    report = evaluate_apiref_recall(
        retriever=ApiRefRetriever(store=store), scope=scope0, cases=cases
    )
    assert report.per_type_recall_at5["exact_fqn"] == 1.0
    assert report.recall_at[5] >= 0.9, report.misses

    # Latency sanity: a batch of mixed queries stays well under a loose bound.
    start = time.perf_counter()
    for c in range(50):
        store.get_symbol(member_fqn=f"scale.p0.Class{c}.Method1", scope=scope0)
        store.list_members(parent_fqn=f"scale.p0.Class{c}", scope=scope0)
    elapsed = time.perf_counter() - start
    assert elapsed < 15.0, f"100 indexed queries took {elapsed:.1f}s"
