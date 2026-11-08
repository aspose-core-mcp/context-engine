"""Regression tests for the OpenSearch backfill script's DR-restore wiring.

Pins the three edits made so the backfill is usable as the lexical-lane step of
a disaster-recovery restore:

1. It honours ``QDRANT_URL`` / ``OPENSEARCH_URL`` from the environment (the
   docstring always claimed this but the code hardcoded ``localhost``).
2. ``COLLECTION_MAP`` targets ONLY the EN docs collection — the retired
   ``apiref_dense_v1`` vector collection is no longer backfilled (apiref is served
   from the Postgres structured store).
3. The docs collection name is settings-driven via ``DOCS_VECTOR_COLLECTION``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "backfill_opensearch_from_qdrant.py"
)


def _load(monkeypatch: pytest.MonkeyPatch, **env: str) -> ModuleType:
    """Import the backfill script fresh with the given environment."""
    for key in ("QDRANT_URL", "OPENSEARCH_URL", "DOCS_VECTOR_COLLECTION"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("backfill_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_honours_qdrant_and_opensearch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(
        monkeypatch,
        QDRANT_URL="http://qdrant.internal:16333",
        OPENSEARCH_URL="http://opensearch.internal:19200",
    )
    assert module.QDRANT_URL == "http://qdrant.internal:16333"
    assert module.OPENSEARCH_URL == "http://opensearch.internal:19200"


def test_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(monkeypatch)
    assert module.QDRANT_URL == "http://localhost:6333"
    assert module.OPENSEARCH_URL == "http://localhost:9200"


def test_collection_map_is_docs_en_only(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(monkeypatch)
    collection_map = module.COLLECTION_MAP
    assert set(collection_map) == {"docs_dense_en_v1"}
    # The retired / legacy collections must not be backfilled.
    assert "apiref_dense_v1" not in collection_map
    assert "docs_dense_v1" not in collection_map
    entry = collection_map["docs_dense_en_v1"]
    assert entry["alias"] == "docs_lex_v1_active"
    assert entry["index"] == "docs_lex_v1_consolidated"
    assert entry["source_kind"] == "docs"


def test_collection_name_is_settings_driven(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(monkeypatch, DOCS_VECTOR_COLLECTION="docs_dense_custom")
    assert set(module.COLLECTION_MAP) == {"docs_dense_custom"}


class _FakeResponse:
    """Minimal stand-in for the object ``urllib.request.urlopen`` yields."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _stub_urlopen(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, body: bytes, status: int = 200
) -> None:
    def _fake(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(body, status)

    monkeypatch.setattr(module.request, "urlopen", _fake)


@pytest.mark.parametrize("helper", ["http_request", "http_request_ndjson"])
def test_non_json_body_is_returned_as_text(
    monkeypatch: pytest.MonkeyPatch, helper: str
) -> None:
    """The ``_cat`` APIs answer in plain text — that must not raise.

    The final verification of a restore calls ``_cat/indices?v&s=index``
    through this helper; unconditionally running ``json.loads`` there ends
    EVERY backfill run in a JSONDecodeError traceback — masking real failures.
    """
    module = _load(monkeypatch)
    cat_body = b"health status index\ngreen  open   docs_lex_v1_consolidated 37067\n"
    _stub_urlopen(monkeypatch, module, cat_body)
    fn = getattr(module, helper)
    url = "http://os.invalid/_cat/indices?v"
    # the ndjson variant takes the payload as a second positional argument
    status, body = fn(url, b"") if helper == "http_request_ndjson" else fn(url)
    assert status == 200
    assert isinstance(body, str)
    assert "docs_lex_v1_consolidated" in body


def test_json_body_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(monkeypatch)
    _stub_urlopen(monkeypatch, module, b'{"count": 37067}')
    status, body = module.http_request("http://os.invalid/_count")
    assert status == 200
    assert body == {"count": 37067}


def test_empty_body_is_an_empty_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(monkeypatch)
    _stub_urlopen(monkeypatch, module, b"   ")
    status, body = module.http_request("http://os.invalid/whatever")
    assert status == 200
    assert body == {}
