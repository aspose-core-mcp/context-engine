"""Admin API endpoint for per-product docs + apiref coverage.

Backs the admin "Coverage" page: one row per registered Aspose/GroupDocs
product with its live docs chunk count (Qdrant, ``settings.docs_vector_collection``
— default ``docs_dense_en_v1``), apiref symbol
count (Postgres ``symbols``), the backing GitHub repos, and derived gap flags.

Mirrors ``admin_index_status`` (same auth, same Qdrant POST-count helper); adds
a cached SQLAlchemy engine for the per-product symbol GROUP BY.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from adcs.api.admin_auth import require_admin_principal
from adcs.api.admin_index_status import (
    _get_settings,
    _query_qdrant_product_count,
    _source_registry,
)
from adcs.ingestion.source_registry import SourceRegistryService

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["admin-product-coverage"],
    dependencies=[Depends(require_admin_principal)],
)

# A product that HAS a docs repo but indexes fewer than this many chunks is
# flagged "docs_thin" (e.g. an empty/partial clone), distinct from "docs_missing".
_DOCS_THIN_THRESHOLD = 300


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ProductCoverageRow(BaseModel):
    product_id: str
    product_name: str
    family: str
    docs_chunks: int = 0
    apiref_symbols: int = 0
    docs_repo: str | None = None
    apiref_repo: str | None = None
    gaps: list[str] = Field(default_factory=list)


class ProductCoverageSummary(BaseModel):
    total_products: int = 0
    products_with_docs: int = 0
    products_with_apiref: int = 0
    products_fully_covered: int = 0
    total_docs_chunks: int = 0
    total_apiref_symbols: int = 0


class ProductCoverageResponse(BaseModel):
    rows: list[ProductCoverageRow] = Field(default_factory=list)
    summary: ProductCoverageSummary = Field(default_factory=ProductCoverageSummary)
    generated_at: str = ""
    postgres_error: str | None = None


# ---------------------------------------------------------------------------
# Postgres symbol counts
# ---------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _symbol_engine(dsn: str) -> object:
    from sqlalchemy import create_engine

    return create_engine(dsn, pool_pre_ping=True)


def _symbol_counts(dsn: str) -> tuple[dict[str, int], str | None]:
    """Return ``{product_id: symbol_count}`` from the Postgres symbol store."""
    from sqlalchemy import text

    try:
        engine = _symbol_engine(dsn)
        with engine.connect() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                text("SELECT product, count(*) AS n FROM symbols GROUP BY product")
            )
            return {str(product): int(n) for product, n in rows}, None
    except Exception as exc:
        logger.warning("Symbol count query failed: %s", exc, exc_info=True)
        return {}, f"Postgres unreachable or error: {exc}"


# ---------------------------------------------------------------------------
# Registry → per-product repo metadata
# ---------------------------------------------------------------------------


def _repo_name(url: str | None) -> str | None:
    """``https://github.com/org/Repo.git`` -> ``org/Repo``."""
    if not url:
        return None
    trimmed = url.rstrip("/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[: -len(".git")]
    parts = trimmed.split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return parts[-1] if parts else None


def _registry_product_info(
    registry: SourceRegistryService,
) -> dict[str, dict[str, object]]:
    """Collapse the repo list into one record per product_id."""
    info: dict[str, dict[str, object]] = {}
    for repo in registry.list_repositories():
        pid = repo.product_id
        record = info.setdefault(
            pid,
            {
                "product_name": repo.product_name,
                "family": repo.product_family,
                "docs_repo": None,
                "apiref_repo": None,
            },
        )
        repo_name = _repo_name(getattr(repo.git, "url", None))
        if repo.source_kind == "docs" and record["docs_repo"] is None:
            record["docs_repo"] = repo_name
        elif repo.source_kind == "apiref" and record["apiref_repo"] is None:
            record["apiref_repo"] = repo_name
    return info


def _gaps(*, docs_repo: object, apiref_repo: object, docs: int, apiref: int) -> list[str]:
    gaps: list[str] = []
    if docs_repo is None:
        gaps.append("no_docs_source")
    elif docs == 0:
        gaps.append("docs_missing")
    elif docs < _DOCS_THIN_THRESHOLD:
        gaps.append("docs_thin")
    if apiref_repo is None:
        gaps.append("no_apiref_source")
    elif apiref == 0:
        gaps.append("apiref_missing")
    return gaps


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/admin/v1/product-coverage",
    response_model=ProductCoverageResponse,
    summary="Per-product docs + apiref coverage",
)
def get_product_coverage(request_obj: Request) -> ProductCoverageResponse:
    """Return one coverage row per registered product (docs + apiref)."""
    settings = _get_settings(request_obj)
    registry = _source_registry(request_obj)
    qdrant_url = settings.qdrant_url.rstrip("/")

    info = _registry_product_info(registry)
    symbol_counts, postgres_error = _symbol_counts(settings.postgres_dsn)

    rows: list[ProductCoverageRow] = []
    for pid in sorted(info):
        meta = info[pid]
        try:
            docs = _query_qdrant_product_count(qdrant_url, settings.docs_vector_collection, pid)
        except Exception:
            # The Coverage page must render even when Qdrant is transiently
            # unreachable — degrade the docs count to 0 rather than 500 the page.
            logger.warning("docs count query failed for %s; defaulting to 0", pid)
            docs = 0
        apiref = symbol_counts.get(pid, 0)
        rows.append(
            ProductCoverageRow(
                product_id=pid,
                product_name=str(meta["product_name"]),
                family=str(meta["family"]),
                docs_chunks=docs,
                apiref_symbols=apiref,
                docs_repo=meta["docs_repo"],  # type: ignore[arg-type]
                apiref_repo=meta["apiref_repo"],  # type: ignore[arg-type]
                gaps=_gaps(
                    docs_repo=meta["docs_repo"],
                    apiref_repo=meta["apiref_repo"],
                    docs=docs,
                    apiref=apiref,
                ),
            )
        )

    summary = ProductCoverageSummary(
        total_products=len(rows),
        products_with_docs=sum(1 for r in rows if r.docs_chunks > 0),
        products_with_apiref=sum(1 for r in rows if r.apiref_symbols > 0),
        products_fully_covered=sum(
            1 for r in rows if r.docs_chunks > 0 and r.apiref_symbols > 0
        ),
        total_docs_chunks=sum(r.docs_chunks for r in rows),
        total_apiref_symbols=sum(r.apiref_symbols for r in rows),
    )

    return ProductCoverageResponse(
        rows=rows,
        summary=summary,
        generated_at=datetime.now(UTC).isoformat(),
        postgres_error=postgres_error,
    )
