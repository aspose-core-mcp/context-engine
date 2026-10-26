"""#135689: canonical namespace casing survives the isolated plugin/engine boundary."""

from __future__ import annotations

import json

import pytest

from adcs.api.apiref_symbol_query import ApiRefSymbolService
from adcs.indexing.apiref_symbol_store import InMemoryApiRefSymbolStore
from adcs.mcp.tool_gateway import MCPToolGateway
from test_product_platform_plugins import prepare
from test_public_query_structured_symbol_doc import _service

CASES = [
    (
        "aspose.words.ai",
        "Aspose.Words.AI",
        "aimodel",
        "AiModel class",
        "public class AiModel",
        "AiModel",
    ),
    (
        "aspose.words.ai",
        "Aspose.Words.AI",
        "aimodel/checkgrammar",
        "AiModel.CheckGrammar method",
        "public void CheckGrammar()",
        "AiModel.CheckGrammar",
    ),
    (
        "aspose.words.digitalsignatures",
        "Aspose.Words.DigitalSignatures",
        "digitalsignatureutil",
        "DigitalSignatureUtil class",
        "public class DigitalSignatureUtil",
        "DigitalSignatureUtil",
    ),
    (
        "aspose.words.ai",
        "Aspose.Words.AI",
        "aimodel/aimodel",
        "AiModel constructor",
        "public AiModel()",
        "AiModel.AiModel",
    ),
]


@pytest.mark.parametrize("slug,namespace,tail,heading,signature,suffix", CASES)
def test_namespace_identity_through_engine_worker_and_symbol_export(
    tmp_path,
    monkeypatch,
    slug,
    namespace,
    tail,
    heading,
    signature,
    suffix,
):
    worker, _, sources = prepare(tmp_path, kinds=("apiref",))
    source = sources[0]
    root = tmp_path / source.git.submodule_path
    directory = root / "english/net" / slug
    directory.mkdir(parents=True)
    (directory / "_index.md").write_text(f"---\ntitle: {namespace}\n---\n")
    relative = f"english/net/{slug}/{tail}/_index.md"
    page_path = root / relative
    page_path.parent.mkdir(parents=True)
    raw = f"---\ntitle: {heading}\n---\n## {heading}\n```csharp\n{signature}\n```\n"
    page_path.write_text(raw)
    # Discovery's explicit workspace must remain authoritative even if cwd is elsewhere.
    requests = []
    invoke = worker.invoke

    def capture(kind, **payload):
        requests.append(payload)
        return invoke(kind, **payload)

    monkeypatch.setattr(worker, "invoke", capture)
    try:
        worker.discover(repo_root=root, repository=source)
        _, document, chunks = worker.extract(
            repository=source,
            source_path=(source.git.submodule_path / relative).as_posix(),
            relative_repo_path=relative,
            raw_markdown=raw,
            source_revision="namespace-fixture",
        )
        assert requests[-1]["repo_root"] == str(root.resolve())
        expected = namespace + "." + suffix
        assert document.document.symbol_fqn == expected
        assert chunks and all(c.symbol_fqn == expected for c in chunks)
        worker.accept(repository=source, document=document)
        worker.export_symbols(tmp_path / "export")
        symbols = [
            json.loads(line)
            for line in (tmp_path / "export" / f"{source.repo_id}.jsonl").read_text().splitlines()
        ]
        assert symbols
        for symbol in symbols:
            assert symbol["member_fqn"] == expected
            assert symbol["parent_fqn"] == expected.rsplit(".", 1)[0]
            assert symbol["signature"] == signature
            assert (
                symbol["canonical_url"] == f"https://reference.aspose.com/words/net/{slug}/{tail}/"
            )
        # Activate the extracted records and exercise real MCP dispatch locally.
        store = InMemoryApiRefSymbolStore()
        worker.publish_symbols(repo_id=source.repo_id, snapshot_id="namespace-fixture", store=store)
        gateway = MCPToolGateway(
            public_query_service=_service(store),
            apiref_symbol_service=ApiRefSymbolService(store=store),
            supported_revisions=("2024-11-05",),
            primary_revision="2024-11-05",
        )
        session = gateway.initialize(requested_revision="2024-11-05")
        scope = {"product_id": "aspose.words", "language": "net"}
        search = gateway.call_tool(
            session_id=session.session_id,
            tool_name="search_symbols",
            arguments={**scope, "query": suffix.rsplit(".", 1)[-1]},
        )
        assert expected in {row["member_fqn"] for row in search["results"]}
        doc = gateway.call_tool(
            session_id=session.session_id,
            tool_name="get_symbol_doc",
            arguments={**scope, "symbol_fqn": expected},
        )
        assert doc["symbol_fqn"] == expected
        assert doc["signature"] == signature
        assert doc["citations"][0]["canonical_url"] == symbols[0]["canonical_url"]
        members = gateway.call_tool(
            session_id=session.session_id,
            tool_name="list_members",
            arguments={**scope, "parent_fqn": expected.rsplit(".", 1)[0]},
        )
        assert expected in {row["member_fqn"] for row in members["members"]}
    finally:
        worker.close()
