"""REST endpoints for the structured API-reference symbol store.

REST parity for the MCP tools get_symbol / list_members / search_symbols,
backed by the Postgres :class:`ApiRefSymbolService`. These are additive to the
legacy ``/v1/symbols:get`` dense-vector path (``get_symbol_doc``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from adcs.api.apiref_symbol_query import (
    ApiRefSymbolService,
    GetSymbolRequest,
    GetSymbolResponse,
    ListMembersRequest,
    ListMembersResponse,
    LookupRequest,
    LookupResponse,
    SearchSymbolsRequest,
    SearchSymbolsResponse,
)
from adcs.api.error_codes import (
    DEPENDENCY_UNAVAILABLE,
    HTTP_STATUS_BY_CODE,
    NOT_FOUND,
)
from adcs.api.public_docs_query import _enforce_abuse_guard

router = APIRouter(tags=["public-apiref-symbols"])


def _error(
    *, request: Request, code: str, message: str, details: dict[str, object] | None = None,
) -> HTTPException:
    """The standard public error envelope.

    These four routes used to raise `HTTPException(detail="...")` with a bare
    string, so the four structured-symbol endpoints answered in a shape no
    other public route uses and no client could parse uniformly.
    """
    return HTTPException(
        status_code=HTTP_STATUS_BY_CODE[code],
        detail={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def _service(request: Request) -> ApiRefSymbolService:
    service = getattr(request.app.state, "apiref_symbol_service", None)
    if service is None:
        raise _error(
            request=request,
            code=DEPENDENCY_UNAVAILABLE,
            message="API-reference symbol store is not configured.",
        )
    return service


@router.post("/v1/symbols/structured:get", response_model=GetSymbolResponse)
async def get_symbol(request_payload: GetSymbolRequest, request: Request) -> GetSymbolResponse:
    _enforce_abuse_guard(request)
    response = _service(request).get_symbol(request=request_payload)
    if not response.found:
        raise _error(
            request=request,
            code=NOT_FOUND,
            message=f"Symbol `{request_payload.symbol_fqn}` was not found.",
            details={
                "requested_symbol": request_payload.symbol_fqn,
                "suggested_symbols": response.suggested_symbols,
            },
        )
    return response


@router.post("/v1/symbols/structured:members", response_model=ListMembersResponse)
async def list_members(
    request_payload: ListMembersRequest, request: Request
) -> ListMembersResponse:
    _enforce_abuse_guard(request)
    return _service(request).list_members(request=request_payload)


@router.post("/v1/symbols/structured:search", response_model=SearchSymbolsResponse)
async def search_symbols(
    request_payload: SearchSymbolsRequest, request: Request
) -> SearchSymbolsResponse:
    _enforce_abuse_guard(request)
    return _service(request).search_symbols(request=request_payload)


@router.post("/v1/symbols/structured:lookup", response_model=LookupResponse)
async def lookup(request_payload: LookupRequest, request: Request) -> LookupResponse:
    """Forgiving lookup: resolve the product, then search or fetch the symbol in one call."""
    _enforce_abuse_guard(request)
    return _service(request).lookup(request=request_payload)
