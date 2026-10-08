"""get_symbol_doc cutover to the Postgres structured store (ADR-011).

When a PublicQueryService is built with an apiref_symbol_store, get_symbol_doc
must answer from the structured store and fall back to the legacy dense path
only when the structured store has no match (or no concrete version).
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence

import pytest

from adcs.api.public_docs_query import GetSymbolDocRequest, PublicQueryService
from adcs.indexing.apiref_symbol_store import ApiRefScope, ApiRefSymbol
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.retrieval.translation_fallback import TranslationFallbackService


class _FakeSymbolStore:
    """Minimal ApiRefSymbolStore returning preset overloads for get_symbol."""

    def __init__(
        self, *, overloads: Sequence[ApiRefSymbol], active_version: str | None = "25.1"
    ) -> None:
        self._overloads = tuple(overloads)
        self.calls: list[tuple[str, ApiRefScope]] = []
        self.active_version = active_version
        self.resolve_calls: list[tuple[str, str, str]] = []

    def ping(self) -> None:  # pragma: no cover - unused
        return None

    def upsert_symbols(self, symbols: Sequence[ApiRefSymbol]) -> int:  # pragma: no cover
        return 0

    def flip_active_snapshot(  # pragma: no cover
        self, *, scope: ApiRefScope, snapshot_id: str
    ) -> None:
        return None

    def get_symbol(
        self, *, member_fqn: str, scope: ApiRefScope
    ) -> tuple[ApiRefSymbol, ...]:
        self.calls.append((member_fqn, scope))
        return tuple(s for s in self._overloads if s.member_fqn == member_fqn)

    def list_members(
        self, *, parent_fqn: str, scope: ApiRefScope
    ) -> tuple[ApiRefSymbol, ...]:  # pragma: no cover
        return ()

    def search_symbols(
        self, *, pattern: str, scope: ApiRefScope, limit: int
    ) -> tuple[ApiRefSymbol, ...]:  # pragma: no cover
        return ()

    def fts_search(
        self, *, query: str, scope: ApiRefScope, limit: int
    ) -> tuple[ApiRefSymbol, ...]:  # pragma: no cover
        return ()

    def list_overloads(
        self, *, member_fqn: str, scope: ApiRefScope
    ) -> tuple[ApiRefSymbol, ...]:  # pragma: no cover
        return ()

    def resolve_active_version(
        self, *, product: str, language: str, locale: str = "en"
    ) -> str | None:
        self.resolve_calls.append((product, language, locale))
        return self.active_version


def _symbol(**overrides: object) -> ApiRefSymbol:
    base: dict[str, object] = {
        "snapshot_id": "snap-1",
        "product": "aspose.slides",
        "language": "net",
        "version": "25.1",
        "locale": "en",
        "kind": "method",
        "member_fqn": "Aspose.Slides.Presentation.Save",
        "name": "Save",
        "parent_fqn": "Aspose.Slides.Presentation",
        "signature": "public void Save(string file, SaveFormat format)",
        "canonical_url": "https://reference.aspose.com/slides/net/aspose.slides/presentation/save/",
        "is_deprecated": False,
        "summary": "Saves the presentation to a file in the specified format.",
        "payload": {
            "examples": ["presentation.Save(\"out.pptx\", SaveFormat.Pptx);"],
            "section_anchor": "#save",
        },
    }
    base.update(overrides)
    return ApiRefSymbol(**base)  # type: ignore[arg-type]


def _service(store: _FakeSymbolStore | None) -> PublicQueryService:
    # Point the orchestrator at an EMPTY workspace so the legacy fallback's
    # `get_latest_chunk_records` finds nothing deterministically — modelling
    # a deployment, where the legacy apiref path has no local staging. Without this the
    # fallback read the repo's real `data-apiref/` staging (populated by any
    # local re-ingest), making the no-active-version test depend on machine
    # state — it passed on a clean checkout and failed after a local ingest.
    empty_workspace = tempfile.mkdtemp(prefix="adcs-empty-ws-")
    return PublicQueryService(
        source_hugo_normalization_orchestrator=SourceHugoNormalizationOrchestrationService(
            workspace_root=empty_workspace
        ),
        translation_fallback_service=TranslationFallbackService(),
        apiref_symbol_store=store,
    )


def test_get_symbol_doc_answers_from_structured_store() -> None:
    store = _FakeSymbolStore(overloads=[_symbol()])
    service = _service(store)

    response = service.get_symbol_doc(
        request=GetSymbolDocRequest(
            product_id="aspose.slides",
            language="net",
            version="25.1",
            symbol_fqn="Aspose.Slides.Presentation.Save",
        )
    )

    assert response.symbol_fqn == "Aspose.Slides.Presentation.Save"
    assert response.signature == "public void Save(string file, SaveFormat format)"
    assert "Saves the presentation" in response.summary
    assert [p.name for p in response.parameters] == ["file", "format"]
    assert response.examples[0].code == 'presentation.Save("out.pptx", SaveFormat.Pptx);'
    # Citation carries the structured canonical_url + payload section anchor.
    assert response.citations[0].canonical_url.endswith("/presentation/save/")
    assert response.citations[0].section_anchor == "#save"
    assert response.signature_variants[0].source_kind == "apiref"
    # The store was scoped to the requested product/language/version.
    assert store.calls[0][1] == ApiRefScope(
        product="aspose.slides", language="net", version="25.1", locale="en"
    )


def test_get_symbol_doc_prefers_typed_examples_over_legacy_chunk_text() -> None:
    symbol = _symbol(payload={
        "examples": ["prose and See Also must not be returned"],
        "example_snippets": [{"language": "csharp", "code": "var doc = new Document();"}],
    })
    response = _service(_FakeSymbolStore(overloads=[symbol])).get_symbol_doc(
        request=GetSymbolDocRequest(
            product_id="aspose.slides", language="net",
            symbol_fqn=symbol.member_fqn,
        )
    )
    assert [(e.language, e.code) for e in response.examples] == [
        ("csharp", "var doc = new Document();")
    ]


def test_get_symbol_doc_marks_deprecated_from_structured_store() -> None:
    store = _FakeSymbolStore(overloads=[_symbol(is_deprecated=True)])
    service = _service(store)

    response = service.get_symbol_doc(
        request=GetSymbolDocRequest(
            product_id="aspose.slides",
            language="net",
            version="25.1",
            symbol_fqn="Aspose.Slides.Presentation.Save",
        )
    )

    assert response.deprecated is True
    assert any("deprecated" in rule.casefold() for rule in response.guardrails)


def test_structured_lookup_skipped_when_scope_has_no_active_version() -> None:
    """Only give up when the scope genuinely has nothing active.

    A versionless request resolves the active version — see
    test_get_symbol_doc_without_version_resolves_the_active_version. Skipping
    the structured store outright would be a dead end: the retired
    ``apiref_dense_v1`` collection cannot catch the fallback, so symbols that
    are in Postgres would come back NOT_FOUND.
    """
    store = _FakeSymbolStore(overloads=[_symbol()], active_version=None)
    service = _service(store)

    result = service._structured_get_symbol_doc(
        request=GetSymbolDocRequest(
            product_id="aspose.slides",
            language="net",
            version=None,
            symbol_fqn="Aspose.Slides.Presentation.Save",
        )
    )
    assert result is None
    assert store.calls == []


def test_structured_lookup_returns_none_on_miss() -> None:
    store = _FakeSymbolStore(overloads=[_symbol()])
    service = _service(store)

    result = service._structured_get_symbol_doc(
        request=GetSymbolDocRequest(
            product_id="aspose.slides",
            language="net",
            version="25.1",
            symbol_fqn="Aspose.Slides.Presentation.Unknown",
        )
    )
    assert result is None


def test_get_symbol_doc_without_version_resolves_the_active_version() -> None:
    """A versionless request must still answer from the structured store.

    ``version`` is optional on the public contract and MCP callers rarely know a
    concrete SDK version, so bailing out when it is absent would send every such
    request down the legacy dense path. That path targets the RETIRED
    ``apiref_dense_v1`` collection, which does not exist in a current deployment,
    so ``get_symbol_doc`` — one of the five core MCP tools — would answer
    NOT_FOUND for symbols present in Postgres all along (while passing
    ``version=latest-stable`` returns the symbol fine).
    """
    store = _FakeSymbolStore(overloads=[_symbol()], active_version="25.1")
    service = _service(store)

    response = service.get_symbol_doc(
        request=GetSymbolDocRequest(
            product_id="aspose.slides",
            language="net",
            symbol_fqn="Aspose.Slides.Presentation.Save",
        )
    )

    assert response.symbol_fqn == "Aspose.Slides.Presentation.Save"
    assert response.signature == "public void Save(string file, SaveFormat format)"
    # The active version was resolved and used to scope the lookup.
    assert store.resolve_calls == [("aspose.slides", "net", "en")]
    assert store.calls[0][1] == ApiRefScope(
        product="aspose.slides", language="net", version="25.1", locale="en"
    )


def test_get_symbol_doc_falls_back_when_no_active_version_exists() -> None:
    """With nothing active for the scope, keep the legacy fallback behaviour.

    The legacy path has no data in this fixture, so the symbol is genuinely
    unresolvable and a LookupError (surfaced as NOT_FOUND) is the honest
    answer — the point is that resolution was attempted, not skipped.
    """
    store = _FakeSymbolStore(overloads=[_symbol()], active_version=None)
    service = _service(store)

    with pytest.raises(LookupError):
        service.get_symbol_doc(
            request=GetSymbolDocRequest(
                product_id="aspose.slides",
                language="net",
                symbol_fqn="Aspose.Slides.Presentation.Save",
            )
        )
    # The structured store was consulted for an active version before falling back.
    assert store.resolve_calls == [("aspose.slides", "net", "en")]
