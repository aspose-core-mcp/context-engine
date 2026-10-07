"""One JSON request per isolated process. No engine or sibling-plugin imports."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from adcs_tex_net import apiref_extractor, docs_extractor
from adcs_tex_net.chunking import StageDChunkingPolicy
from adcs_tex_net.normalized_document import HugoToNormalizedDocumentConverter
from adcs_tex_net.symbols import extract_symbol

CONTRACT = "adcs.extraction.v1"
PLUGIN_ID = "aspose.tex.net"
VERSION = "0.1.0"


def handle(request):
    if request.get("contract") != CONTRACT or request.get("plugin_id") != PLUGIN_ID:
        raise ValueError("Unsupported extraction contract or plugin identity")
    if request.get("product_id") != "aspose.tex" or request.get("language") != "net":
        raise ValueError("Product/platform scope mismatch")
    if request.get("source_kind") not in ("docs", "apiref"):
        raise ValueError("Unsupported source kind")
    if request["operation"] == "discover":
        root = Path(request["repo_root"]).resolve(strict=True)
        prefix = Path(request["source_prefix"])
        if prefix.is_absolute() or ".." in prefix.parts or not prefix.parts:
            raise ValueError("Source prefix must be a relative platform directory")
        selected = (root / prefix).resolve(strict=True)
        if not selected.is_relative_to(root) or not selected.is_dir():
            raise ValueError("Source prefix escapes repository")
        # Each plugin owns discovery; no fallback to all products/languages.
        files = sorted(
            p.relative_to(root).as_posix()
            for p in selected.rglob("*.md")
            if p.is_file() and p.resolve().is_relative_to(selected)
        )
        if not files:
            raise ValueError("No eligible Markdown files in configured platform scope")
        return {"files": files}
    if request["operation"] != "extract":
        raise ValueError("Unsupported operation")
    extractor = docs_extractor if request["source_kind"] == "docs" else apiref_extractor
    page = extractor.extract(request)
    if page.programming_language != "net":
        raise ValueError("Configured layout did not identify .NET content")
    document = HugoToNormalizedDocumentConverter(
        canonical_base_url=request["canonical_base_url"]
    ).convert_page(page=page, source_revision=request["source_revision"])
    document, chunks = StageDChunkingPolicy().chunk_document(
        page=page,
        normalized_document=document,
    )
    symbols = []
    if request["source_kind"] == "apiref":
        symbol = extract_symbol(
            page_chunks=list(chunks),
            snapshot_id="",
            kind_map={document.document.symbol_fqn: document.document.symbol_kind},
        )
        if symbol is not None:
            symbols.append(asdict(symbol))
    return {
        "page": asdict(page),
        "normalized_document": asdict(document),
        "chunk_records": [asdict(chunk) for chunk in chunks],
        "symbols": symbols,
    }


def main():
    try:
        request = json.load(sys.stdin)
        result = handle(request)
        response = {
            "contract": CONTRACT,
            "plugin_id": PLUGIN_ID,
            "plugin_version": VERSION,
            "result": result,
        }
    except Exception as exc:
        response = {
            "contract": CONTRACT,
            "plugin_id": PLUGIN_ID,
            "plugin_version": VERSION,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    print(json.dumps(response, ensure_ascii=False))
    if "error" in response:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
