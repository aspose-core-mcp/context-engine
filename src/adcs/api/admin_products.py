"""Admin API endpoints for product catalog views."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from adcs.api.admin_auth import require_admin_principal
from adcs.ingestion.source_registry import SourceRegistryService

router = APIRouter(
    tags=["admin-products"],
    dependencies=[Depends(require_admin_principal)],
)


class AdminProductResponse(BaseModel):
    product_id: str
    product_family: str
    product_family_dirs: list[str]
    source_kinds: list[str]
    repo_ids: list[str]
    repositories_count: int


def _source_registry(request: Request) -> SourceRegistryService:
    service = getattr(request.app.state, "source_registry_service", None)
    if not isinstance(service, SourceRegistryService):
        msg = "Source registry service is not configured."
        raise RuntimeError(msg)
    return service


@router.get("/admin/v1/products", response_model=list[AdminProductResponse])
def list_products(
    request: Request,
    product_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[AdminProductResponse]:
    repositories = _source_registry(request).list_repositories()
    grouped_repo_ids: dict[str, list[str]] = defaultdict(list)
    grouped_source_kinds: dict[str, set[str]] = defaultdict(set)
    grouped_product_family: dict[str, str] = {}
    grouped_product_family_dirs: dict[str, set[str]] = defaultdict(set)

    for repository in repositories:
        if product_id is not None and repository.product_id != product_id:
            continue
        grouped_repo_ids[repository.product_id].append(repository.repo_id)
        grouped_source_kinds[repository.product_id].add(repository.source_kind)
        grouped_product_family.setdefault(repository.product_id, repository.product_family)
        grouped_product_family_dirs[repository.product_id].add(repository.product_family_dir)

    rows: list[AdminProductResponse] = []
    for current_product_id in sorted(grouped_repo_ids):
        repo_ids = sorted(grouped_repo_ids[current_product_id])
        rows.append(
            AdminProductResponse(
                product_id=current_product_id,
                product_family=grouped_product_family.get(current_product_id, current_product_id),
                product_family_dirs=sorted(grouped_product_family_dirs[current_product_id]),
                source_kinds=sorted(grouped_source_kinds[current_product_id]),
                repo_ids=repo_ids,
                repositories_count=len(repo_ids),
            )
        )

    return rows[:limit]
