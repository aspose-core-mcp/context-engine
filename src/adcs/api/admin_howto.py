"""Admin and public APIs for How-To draft/published overrides."""

from __future__ import annotations

import mimetypes
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from adcs.admin import FileBackedHowToOverrideStore, HowToOverrideEnvelope
from adcs.api.admin_auth import (
    AdminAuthError,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)

router = APIRouter(
    tags=["admin-howto"],
    dependencies=[Depends(require_admin_principal)],
)
public_router = APIRouter(tags=["public-howto"])


class LocalizedTextPayload(BaseModel):
    en: str = ""
    ru: str = ""


class LocalizedLinesPayload(BaseModel):
    en: list[str] = Field(default_factory=list)
    ru: list[str] = Field(default_factory=list)


class HowToCalloutPayload(BaseModel):
    id: str
    level: str
    title: LocalizedTextPayload
    body: LocalizedLinesPayload

    @field_validator("id", "level")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty.")
        return normalized


class HowToCommandPayload(BaseModel):
    id: str
    label: LocalizedTextPayload
    description: LocalizedTextPayload
    command: str

    @field_validator("id", "command")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty.")
        return normalized


class HowToExamplePayload(BaseModel):
    id: str
    title: LocalizedTextPayload
    bullets: LocalizedLinesPayload

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("id must not be empty.")
        return normalized


class HowToScreenshotPayload(BaseModel):
    id: str
    src: str
    alt: LocalizedTextPayload
    caption: LocalizedTextPayload

    @field_validator("id", "src")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty.")
        return normalized


class HowToOverridePayloadRequest(BaseModel):
    entry_label: LocalizedTextPayload = Field(default_factory=LocalizedTextPayload)
    title: LocalizedTextPayload = Field(default_factory=LocalizedTextPayload)
    summary: LocalizedTextPayload = Field(default_factory=LocalizedTextPayload)
    purpose: LocalizedLinesPayload = Field(default_factory=LocalizedLinesPayload)
    workflow: LocalizedLinesPayload = Field(default_factory=LocalizedLinesPayload)
    callouts: list[HowToCalloutPayload] = Field(default_factory=list)
    commands: list[HowToCommandPayload] = Field(default_factory=list)
    examples: list[HowToExamplePayload] = Field(default_factory=list)
    screenshots: list[HowToScreenshotPayload] = Field(default_factory=list)


class HowToOverridePayloadResponse(HowToOverridePayloadRequest):
    pass


class HowToOverrideEnvelopeResponse(BaseModel):
    article_id: str
    draft: HowToOverridePayloadResponse | None
    draft_updated_at: datetime | None
    draft_updated_by: str | None
    published: HowToOverridePayloadResponse | None
    published_updated_at: datetime | None
    published_updated_by: str | None


class HowToOverrideListResponse(BaseModel):
    records: list[HowToOverrideEnvelopeResponse]
    generated_at: datetime


class PublishedHowToArticleResponse(BaseModel):
    article_id: str
    published: HowToOverridePayloadResponse
    published_updated_at: datetime | None
    published_updated_by: str | None


class PublishedHowToListResponse(BaseModel):
    articles: list[PublishedHowToArticleResponse]
    generated_at: datetime


class HowToAssetUploadRequest(BaseModel):
    filename: str
    content_base64: str

    @field_validator("filename", "content_base64")
    @classmethod
    def _validate_upload_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty.")
        return normalized


class HowToAssetUploadResponse(BaseModel):
    asset_name: str
    asset_url: str
    size_bytes: int


def get_howto_override_store(request: Request) -> FileBackedHowToOverrideStore:
    store = getattr(request.app.state, "howto_override_store", None)
    if not isinstance(store, FileBackedHowToOverrideStore):
        raise RuntimeError("How-To override store is not configured.")
    return store


def _normalize_article_id(article_id: str) -> str:
    normalized = article_id.strip()
    if not normalized:
        raise ValueError("article_id must not be empty.")
    return normalized


def _to_http_exception(*, request: Request, error: AdminAuthError) -> HTTPException:
    request_id = getattr(request.state, "request_id", None)
    return HTTPException(
        status_code=error.status_code,
        detail={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": {},
                "request_id": request_id,
            }
        },
    )


def _raise_invalid_request(request: Request, *, code: str, message: str) -> None:
    request_id = getattr(request.state, "request_id", None)
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": request_id,
            }
        },
    )


def _authorize_howto_write(request: Request, principal: AdminKeyPrincipal) -> None:
    service = get_admin_auth_service(request)
    try:
        service.authorize_mutation(
            principal=principal,
            required_scope="write:settings",
            target_product_ids=(),
        )
    except AdminAuthError as exc:
        raise _to_http_exception(request=request, error=exc) from exc


def _serialize_envelope(record: HowToOverrideEnvelope) -> HowToOverrideEnvelopeResponse:
    return HowToOverrideEnvelopeResponse.model_validate(asdict(record))


def _serialize_published(record: HowToOverrideEnvelope) -> PublishedHowToArticleResponse | None:
    if record.published is None:
        return None
    return PublishedHowToArticleResponse.model_validate(
        {
            "article_id": record.article_id,
            "published": asdict(record.published),
            "published_updated_at": record.published_updated_at,
            "published_updated_by": record.published_updated_by,
        }
    )


@router.get("/admin/v1/howto/articles", response_model=HowToOverrideListResponse)
def list_howto_articles(
    request: Request,
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> HowToOverrideListResponse:
    records = sorted(store.list_records(), key=lambda item: item.article_id)
    return HowToOverrideListResponse(
        records=[_serialize_envelope(item) for item in records],
        generated_at=datetime.now(tz=UTC),
    )


@router.get("/admin/v1/howto/articles/{article_id}", response_model=HowToOverrideEnvelopeResponse)
def get_howto_article(
    article_id: str,
    request: Request,
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> HowToOverrideEnvelopeResponse:
    try:
        normalized_article_id = _normalize_article_id(article_id)
    except ValueError as exc:
        _raise_invalid_request(request, code="INVALID_ARTICLE_ID", message=str(exc))
    return _serialize_envelope(store.get_record(normalized_article_id))


@router.put(
    "/admin/v1/howto/articles/{article_id}/draft",
    response_model=HowToOverrideEnvelopeResponse,
)
def upsert_howto_draft(
    article_id: str,
    payload: HowToOverridePayloadRequest,
    request: Request,
    principal: AdminKeyPrincipal = Depends(require_admin_principal),
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> HowToOverrideEnvelopeResponse:
    _authorize_howto_write(request, principal)
    try:
        normalized_article_id = _normalize_article_id(article_id)
    except ValueError as exc:
        _raise_invalid_request(request, code="INVALID_ARTICLE_ID", message=str(exc))
    record = store.upsert_draft(
        article_id=normalized_article_id,
        payload=payload.model_dump(mode="python"),
        actor_key_id=principal.key_id,
    )
    return _serialize_envelope(record)


@router.post(
    "/admin/v1/howto/articles/{article_id}:publish",
    response_model=HowToOverrideEnvelopeResponse,
)
def publish_howto_article(
    article_id: str,
    request: Request,
    principal: AdminKeyPrincipal = Depends(require_admin_principal),
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> HowToOverrideEnvelopeResponse:
    _authorize_howto_write(request, principal)
    try:
        normalized_article_id = _normalize_article_id(article_id)
        record = store.publish(article_id=normalized_article_id, actor_key_id=principal.key_id)
    except ValueError as exc:
        _raise_invalid_request(request, code="INVALID_PUBLISH", message=str(exc))
    return _serialize_envelope(record)


@router.post(
    "/admin/v1/howto/articles/{article_id}:reset-draft",
    response_model=HowToOverrideEnvelopeResponse,
)
def reset_howto_draft(
    article_id: str,
    request: Request,
    principal: AdminKeyPrincipal = Depends(require_admin_principal),
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> HowToOverrideEnvelopeResponse:
    _authorize_howto_write(request, principal)
    try:
        normalized_article_id = _normalize_article_id(article_id)
    except ValueError as exc:
        _raise_invalid_request(request, code="INVALID_ARTICLE_ID", message=str(exc))
    return _serialize_envelope(store.reset_draft(article_id=normalized_article_id))


@router.post(
    "/admin/v1/howto/articles/{article_id}:clear-published",
    response_model=HowToOverrideEnvelopeResponse,
)
def clear_published_howto_article(
    article_id: str,
    request: Request,
    principal: AdminKeyPrincipal = Depends(require_admin_principal),
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> HowToOverrideEnvelopeResponse:
    _authorize_howto_write(request, principal)
    try:
        normalized_article_id = _normalize_article_id(article_id)
    except ValueError as exc:
        _raise_invalid_request(request, code="INVALID_ARTICLE_ID", message=str(exc))
    return _serialize_envelope(store.clear_published(article_id=normalized_article_id))


@router.post("/admin/v1/howto/assets:upload", response_model=HowToAssetUploadResponse)
def upload_howto_asset(
    payload: HowToAssetUploadRequest,
    request: Request,
    principal: AdminKeyPrincipal = Depends(require_admin_principal),
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> HowToAssetUploadResponse:
    _authorize_howto_write(request, principal)
    try:
        asset_name = store.store_asset(
            filename=payload.filename,
            content_base64=payload.content_base64,
        )
    except ValueError as exc:
        _raise_invalid_request(request, code="INVALID_ASSET_UPLOAD", message=str(exc))
    asset_path = store.resolve_asset_path(asset_name)
    return HowToAssetUploadResponse(
        asset_name=asset_name,
        asset_url=f"{str(request.base_url).rstrip('/')}/v1/howto/assets/{asset_name}",
        size_bytes=asset_path.stat().st_size,
    )


@public_router.get("/v1/howto/articles", response_model=PublishedHowToListResponse)
def list_published_howto_articles(
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> PublishedHowToListResponse:
    published_items: list[PublishedHowToArticleResponse] = []
    for record in sorted(store.list_records(), key=lambda item: item.article_id):
        item = _serialize_published(record)
        if item is not None:
            published_items.append(item)
    return PublishedHowToListResponse(
        articles=published_items,
        generated_at=datetime.now(tz=UTC),
    )


@public_router.get("/v1/howto/articles/{article_id}", response_model=PublishedHowToArticleResponse)
def get_published_howto_article(
    article_id: str,
    request: Request,
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> PublishedHowToArticleResponse:
    try:
        normalized_article_id = _normalize_article_id(article_id)
    except ValueError as exc:
        _raise_invalid_request(request, code="INVALID_ARTICLE_ID", message=str(exc))
    item = _serialize_published(store.get_record(normalized_article_id))
    if item is None:
        raise HTTPException(status_code=404, detail="How-To article override was not found.")
    return item


@public_router.get("/v1/howto/assets/{asset_name}")
def get_howto_asset(
    asset_name: str,
    request: Request,
    store: FileBackedHowToOverrideStore = Depends(get_howto_override_store),
) -> FileResponse:
    del request
    try:
        asset_path = store.resolve_asset_path(asset_name)
    except ValueError:
        raise HTTPException(status_code=404, detail="How-To asset was not found.") from None
    if not asset_path.exists() or not asset_path.is_file():
        raise HTTPException(status_code=404, detail="How-To asset was not found.")
    media_type, _ = mimetypes.guess_type(str(asset_path))
    return FileResponse(path=Path(asset_path), media_type=media_type or "application/octet-stream")
