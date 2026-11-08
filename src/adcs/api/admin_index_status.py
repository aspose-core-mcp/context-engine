"""Admin API endpoint for live index status from Qdrant and OpenSearch."""

from __future__ import annotations

import json
import logging
from urllib import error, request

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from adcs.api.admin_auth import require_admin_principal
from adcs.config import Settings
from adcs.ingestion.source_registry import SourceRegistryService

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["admin-index-status"],
    dependencies=[Depends(require_admin_principal)],
)

# Fallback only. The live names come from settings (see _resolve_qdrant_collections)
# so index status reports the collections this deployment actually serves; pinned
# to the retired literals it reported an empty index while retrieval worked fine.
_QDRANT_COLLECTIONS = ("docs_dense_v1", "apiref_dense_v1")
_OPENSEARCH_ALIASES = ("docs_lex_v1_active", "apiref_lex_v1_active")
_REQUEST_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class QdrantCollectionStatus(BaseModel):
    total_points: int = 0
    products: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class OpenSearchAliasStatus(BaseModel):
    total_docs: int = 0
    error: str | None = None


class IndexStatusSummary(BaseModel):
    total_qdrant_points: int = 0
    total_opensearch_docs: int = 0
    products_with_docs: int = 0
    products_with_apiref: int = 0


class IndexStatusResponse(BaseModel):
    qdrant: dict[str, QdrantCollectionStatus] = Field(default_factory=dict)
    opensearch: dict[str, OpenSearchAliasStatus] = Field(default_factory=dict)
    summary: IndexStatusSummary = Field(default_factory=IndexStatusSummary)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_registry(request_obj: Request) -> SourceRegistryService:
    service = getattr(request_obj.app.state, "source_registry_service", None)
    if not isinstance(service, SourceRegistryService):
        msg = "Source registry service is not configured."
        raise RuntimeError(msg)
    return service


def _get_settings(request_obj: Request) -> Settings:
    settings = getattr(request_obj.app.state, "settings", None)
    if not isinstance(settings, Settings):
        msg = "Settings are not configured."
        raise RuntimeError(msg)
    return settings


def _get_product_ids(registry: SourceRegistryService) -> tuple[str, ...]:
    """Extract unique product IDs from the source registry."""
    seen: set[str] = set()
    product_ids: list[str] = []
    for repo in registry.list_repositories():
        if repo.product_id not in seen:
            seen.add(repo.product_id)
            product_ids.append(repo.product_id)
    return tuple(sorted(product_ids))


def _http_get_json(
    url: str,
    *,
    timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
) -> tuple[int, object]:
    """Issue a GET request and return (status_code, parsed_json)."""
    req = request.Request(
        url=url,
        method="GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return response.status, _decode_json(raw)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, _decode_json(raw)
    except error.URLError as exc:
        msg = f"HTTP request failed for {url}: {exc.reason}"
        raise RuntimeError(msg) from exc


def _http_post_json(
    url: str,
    payload: dict[str, object],
    *,
    timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
) -> tuple[int, object]:
    """Issue a POST request with JSON body and return (status_code, parsed_json)."""
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return response.status, _decode_json(raw)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, _decode_json(raw)
    except error.URLError as exc:
        msg = f"HTTP request failed for {url}: {exc.reason}"
        raise RuntimeError(msg) from exc


def _decode_json(raw_body: str) -> object:
    if not raw_body.strip():
        return {}
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body


# ---------------------------------------------------------------------------
# Qdrant queries
# ---------------------------------------------------------------------------


def _query_qdrant_collection_total(
    qdrant_url: str,
    collection_name: str,
) -> int:
    """Return total point count for a Qdrant collection via collection info."""
    status_code, body = _http_get_json(
        f"{qdrant_url}/collections/{collection_name}",
    )
    if status_code == 404:
        return 0
    if status_code != 200 or not isinstance(body, dict):
        return 0
    result = body.get("result")
    if not isinstance(result, dict):
        return 0
    return int(result.get("points_count", 0))


def _query_qdrant_product_count(
    qdrant_url: str,
    collection_name: str,
    product_id: str,
) -> int:
    """Return point count for a specific product_id in a Qdrant collection."""
    status_code, body = _http_post_json(
        f"{qdrant_url}/collections/{collection_name}/points/count",
        payload={
            "filter": {
                "must": [
                    {"key": "product_id", "match": {"value": product_id}},
                ],
            },
            "exact": True,
        },
    )
    if status_code == 404:
        return 0
    if status_code != 200 or not isinstance(body, dict):
        return 0
    result = body.get("result")
    if not isinstance(result, dict):
        return 0
    return int(result.get("count", 0))


def _query_qdrant_collection(
    qdrant_url: str,
    collection_name: str,
    product_ids: tuple[str, ...],
) -> QdrantCollectionStatus:
    """Build full status for one Qdrant collection."""
    try:
        total = _query_qdrant_collection_total(qdrant_url, collection_name)
        products: dict[str, int] = {}
        for pid in product_ids:
            count = _query_qdrant_product_count(qdrant_url, collection_name, pid)
            if count > 0:
                products[pid] = count
        return QdrantCollectionStatus(total_points=total, products=products)
    except Exception as exc:
        logger.warning(
            "Failed to query Qdrant collection %s: %s",
            collection_name,
            exc,
            exc_info=True,
        )
        return QdrantCollectionStatus(
            error=f"Qdrant unreachable or error: {exc}",
        )


# ---------------------------------------------------------------------------
# OpenSearch queries
# ---------------------------------------------------------------------------


def _query_opensearch_alias(
    opensearch_url: str,
    alias_name: str,
) -> OpenSearchAliasStatus:
    """Return doc count for an OpenSearch alias via the count API."""
    try:
        status_code, body = _http_get_json(
            f"{opensearch_url}/{alias_name}/_count",
        )
        if status_code == 404:
            return OpenSearchAliasStatus(total_docs=0)
        if status_code != 200 or not isinstance(body, dict):
            return OpenSearchAliasStatus(
                error=f"OpenSearch returned status {status_code}",
            )
        return OpenSearchAliasStatus(total_docs=int(body.get("count", 0)))
    except Exception as exc:
        logger.warning(
            "Failed to query OpenSearch alias %s: %s",
            alias_name,
            exc,
            exc_info=True,
        )
        return OpenSearchAliasStatus(
            error=f"OpenSearch unreachable or error: {exc}",
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/admin/v1/index-status",
    response_model=IndexStatusResponse,
    summary="Live index status from Qdrant and OpenSearch",
)
def _resolve_qdrant_collections(settings: object) -> tuple[str, str]:
    """Return (docs, apiref) collection names for this deployment."""
    docs = getattr(settings, "docs_vector_collection", None) or _QDRANT_COLLECTIONS[0]
    apiref = getattr(settings, "apiref_vector_collection", None) or _QDRANT_COLLECTIONS[1]
    return str(docs), str(apiref)


def get_index_status(request_obj: Request) -> IndexStatusResponse:
    """Return live point/doc counts from Qdrant collections and OpenSearch aliases."""
    settings = _get_settings(request_obj)
    registry = _source_registry(request_obj)
    product_ids = _get_product_ids(registry)

    qdrant_url = settings.qdrant_url.rstrip("/")
    opensearch_url = settings.opensearch_url.rstrip("/")

    # Query Qdrant collections
    docs_collection, apiref_collection = _resolve_qdrant_collections(settings)
    qdrant_statuses: dict[str, QdrantCollectionStatus] = {}
    for collection_name in dict.fromkeys((docs_collection, apiref_collection)):
        qdrant_statuses[collection_name] = _query_qdrant_collection(
            qdrant_url, collection_name, product_ids
        )

    # Query OpenSearch aliases
    opensearch_statuses: dict[str, OpenSearchAliasStatus] = {}
    for alias_name in _OPENSEARCH_ALIASES:
        opensearch_statuses[alias_name] = _query_opensearch_alias(opensearch_url, alias_name)

    # Build summary
    total_qdrant = sum(
        s.total_points for s in qdrant_statuses.values() if s.error is None
    )
    total_opensearch = sum(
        s.total_docs for s in opensearch_statuses.values() if s.error is None
    )

    docs_status = qdrant_statuses.get(docs_collection)
    apiref_status = qdrant_statuses.get(apiref_collection)
    products_with_docs = (
        len(docs_status.products) if docs_status and docs_status.error is None else 0
    )
    products_with_apiref = (
        len(apiref_status.products) if apiref_status and apiref_status.error is None else 0
    )

    summary = IndexStatusSummary(
        total_qdrant_points=total_qdrant,
        total_opensearch_docs=total_opensearch,
        products_with_docs=products_with_docs,
        products_with_apiref=products_with_apiref,
    )

    return IndexStatusResponse(
        qdrant=qdrant_statuses,
        opensearch=opensearch_statuses,
        summary=summary,
    )
