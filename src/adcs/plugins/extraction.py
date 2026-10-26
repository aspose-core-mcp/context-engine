"""Versioned JSON worker boundary and adapter into existing ADCS staging."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from pydantic import TypeAdapter

from adcs.plugins.catalog import PluginCatalog, SourceDefinition

if TYPE_CHECKING:
    from adcs.ingestion.chunking import StageDChunkRecord
    from adcs.ingestion.hugo_parser import HugoNormalizedPage
    from adcs.ingestion.normalized_document import NormalizedDocument
    from adcs.ingestion.source_registry import SourceRepository


class ExtractionError(ValueError):
    """A plugin failed or returned incompatible/out-of-scope data."""


class PlatformExtractionBackend:
    def __init__(
        self,
        catalog: PluginCatalog,
        plugin_id: str,
        *,
        python: str | None = None,
        timeout: float = 60,
        max_output_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self.manifest = catalog.extractor(plugin_id)
        self.command = catalog.command(plugin_id, python)
        self.directory = catalog.directories[plugin_id]
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self._symbol_spools: dict[str, TextIO] = {}
        self._repo_roots: dict[str, Path] = {}
        self._pending_symbols: tuple[str, list[Any]] | None = None

    def source(self, repository: SourceRepository) -> SourceDefinition:
        source = next(
            (
                item
                for kind, item in self.manifest.sources.items()
                if kind == repository.source_kind
            ),
            None,
        )
        if (
            source is None
            or repository.product_id != self.manifest.product_id
            or (repository.repo_id != source.repo_id)
            or repository.git.submodule_path.as_posix() != source.path
        ):
            raise ExtractionError("Repository is outside the selected plugin scope")
        return source

    def invoke(self, source_kind: str, **payload: Any) -> dict[str, Any]:
        request = {
            **payload,
            "contract": self.manifest.contract,
            "plugin_id": self.manifest.plugin_id,
            "product_id": self.manifest.product_id,
            "language": self.manifest.language,
            "source_kind": source_kind,
        }
        # Do not pass service credentials or PYTHONPATH into extraction workers.
        env = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "TMPDIR", "SYSTEMROOT")
            if key in os.environ
        }
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            try:
                completed = subprocess.run(
                    self.command,
                    input=json.dumps(request).encode(),
                    stdout=output,
                    stderr=errors,
                    cwd=self.directory,
                    env=env,
                    timeout=self.timeout,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ExtractionError(f"Extraction worker unavailable or timed out: {exc}") from exc
            if output.tell() > self.max_output_bytes:
                raise ExtractionError("Extraction response exceeds configured byte limit")
            output.seek(0)
            try:
                response = json.load(output)
            except (ValueError, UnicodeError) as exc:
                raise ExtractionError("Extraction worker returned invalid JSON") from exc
        if not isinstance(response, dict) or (
            response.get("contract"),
            response.get("plugin_id"),
            response.get("plugin_version"),
        ) != (self.manifest.contract, self.manifest.plugin_id, self.manifest.version):
            raise ExtractionError("Extraction response contract, identity or version mismatch")
        if completed.returncode or "error" in response:
            raise ExtractionError(
                f"Extraction failed: {response.get('error', completed.returncode)}"
            )
        from adcs.plugins.contracts import ExtractionResponse

        try:
            ExtractionResponse.model_validate(response)
        except ValueError as exc:
            raise ExtractionError(f"Invalid response schema: {exc}") from exc
        result = response.get("result")
        if not isinstance(result, dict):
            raise ExtractionError("Extraction response must contain a result object")
        return result

    def discover(self, *, repo_root: Path, repository: SourceRepository) -> list[Path]:
        source = self.source(repository)
        root = repo_root.resolve(strict=True)
        selected = (root / source.prefix).resolve(strict=True)
        if not selected.is_relative_to(root):
            raise ExtractionError("Source prefix escapes repository")
        result = self.invoke(
            repository.source_kind,
            operation="discover",
            repo_root=str(root),
            source_prefix=source.prefix,
        )
        paths = result.get("files")
        if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
            raise ExtractionError("Discovery must return a nonempty list of relative paths")
        discovered = []
        for relative in paths:
            candidate = root / relative
            if (
                Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or (not candidate.resolve(strict=True).is_relative_to(selected))
                or not candidate.is_file()
                or candidate.suffix != ".md"
            ):
                raise ExtractionError("Discovery returned an out-of-scope source path")
            discovered.append(candidate)
        if len(set(discovered)) != len(discovered):
            raise ExtractionError("Discovery returned duplicate source paths")
        if repository.repo_id in self._symbol_spools:
            self._symbol_spools[repository.repo_id].close()
        self._symbol_spools[repository.repo_id] = tempfile.TemporaryFile(mode="w+t")
        self._repo_roots[repository.repo_id] = root
        return sorted(discovered)

    def extract(
        self,
        *,
        repository: SourceRepository,
        source_path: str,
        relative_repo_path: str,
        raw_markdown: str,
        source_revision: str,
    ) -> tuple[HugoNormalizedPage, NormalizedDocument, tuple[StageDChunkRecord, ...]]:
        # Imports are intentionally engine-side only. Workers do not import ADCS.
        from adcs.indexing.apiref_symbol_store import ApiRefSymbol
        from adcs.ingestion.chunking import StageDChunkRecord
        from adcs.ingestion.hugo_parser import HugoNormalizedPage
        from adcs.ingestion.normalized_document import (
            NormalizedDocument,
            NormalizedDocumentValidator,
        )

        source = self.source(repository)
        repo_root = self._repo_roots.get(repository.repo_id)
        if repo_root is None:
            repo_root = Path(source.path).resolve(strict=True)
        if (
            Path(relative_repo_path).is_absolute()
            or ".." in Path(relative_repo_path).parts
            or (not Path(relative_repo_path).is_relative_to(source.prefix))
            or source_path != (Path(source.path) / relative_repo_path).as_posix()
        ):
            raise ExtractionError("Extraction requested outside the platform prefix")
        result = self.invoke(
            repository.source_kind,
            operation="extract",
            repo_root=str(repo_root),
            repo_id=repository.repo_id,
            product_family=repository.product_family,
            source_path=source_path,
            relative_repo_path=relative_repo_path,
            layout_detection=source.layout,
            raw_markdown=raw_markdown,
            source_revision=source_revision,
            canonical_base_url=source.canonical_base_url,
            source_prefix=source.prefix,
        )
        try:
            page = TypeAdapter(HugoNormalizedPage).validate_python(result["page"])
            document = TypeAdapter(NormalizedDocument).validate_python(
                result["normalized_document"]
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ExtractionError(f"Malformed extraction result: {exc}") from exc
        try:
            records = TypeAdapter(tuple[StageDChunkRecord, ...]).validate_python(
                result["chunk_records"]
            )
            symbols = TypeAdapter(list[ApiRefSymbol]).validate_python(result["symbols"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ExtractionError(f"Malformed chunk/symbol result: {exc}") from exc
        expected = (
            repository.repo_id,
            self.manifest.product_id,
            self.manifest.language,
            repository.source_kind,
            source_path,
        )
        scoped_items: tuple[Any, ...] = (page, document.document, *records)
        for item in scoped_items:
            actual = (
                item.repo_id,
                item.product_id,
                item.programming_language,
                item.source_kind,
                item.source_path,
            )
            if actual != expected or item.product_family != repository.product_family:
                raise ExtractionError("Worker returned content outside the requested scope")
        if document.document.source_revision != source_revision:
            raise ExtractionError("Worker changed source provenance")
        if page.doc_locale != document.document.doc_locale:
            raise ExtractionError("Worker returned inconsistent locale metadata")
        NormalizedDocumentValidator().validate_or_raise(document, input_source_path=source_path)
        if not records or len(records) != len(document.chunks):
            raise ExtractionError("Chunk records must match normalized document chunks")
        for record, chunk in zip(records, document.chunks, strict=True):
            if (
                record.source_revision != source_revision
                or record.text != chunk.text
                or (
                    record.chunk_type != chunk.chunk_type
                    or record.canonical_url != chunk.canonical_url
                )
                or record.version != document.document.version
            ):
                raise ExtractionError("Inconsistent chunk provenance or content")
        for symbol in symbols:
            if repository.source_kind != "apiref" or (
                symbol.product,
                symbol.language,
                symbol.version,
            ) != (self.manifest.product_id, self.manifest.language, document.document.version):
                raise ExtractionError("Worker returned an out-of-scope symbol")
        if document.document.doc_type == "api_reference_symbol" and not symbols:
            raise ExtractionError("API symbol document has no structured symbol output")
        self._pending_symbols = (source_path, symbols)
        return page, document, records

    def accept(self, repository: SourceRepository, document: NormalizedDocument) -> None:
        """Only retain symbols after the engine accepts the page for staging."""
        if (
            self._pending_symbols is None
            or self._pending_symbols[0] != document.document.source_path
        ):
            raise ExtractionError("No matching pending extraction")
        spool = self._symbol_spools[repository.repo_id]
        for symbol in self._pending_symbols[1]:
            # Engine URL remapping changes provenance, never re-parses plugin facets.
            symbol = replace(symbol, canonical_url=document.document.canonical_url)
            spool.write(json.dumps(asdict(symbol)) + "\n")
        spool.flush()
        self._pending_symbols = None

    def publish_symbols(self, *, repo_id: str, snapshot_id: str, store: Any) -> None:
        from adcs.indexing.apiref_symbol_store import ApiRefScope, ApiRefSymbol

        spool = self._symbol_spools[repo_id]
        spool.seek(0)
        scopes = set()
        written = 0
        for line in spool:
            symbol = TypeAdapter(ApiRefSymbol).validate_json(line)
            symbol = replace(symbol, snapshot_id=snapshot_id)
            written += store.upsert_symbols([symbol])
            scopes.add(
                ApiRefScope(
                    product=symbol.product,
                    language=symbol.language,
                    version=symbol.version,
                    locale=symbol.locale,
                )
            )
        if not written:
            raise ExtractionError("No accepted structured symbols to publish")
        for scope in scopes:
            store.flip_active_snapshot(scope=scope, snapshot_id=snapshot_id)

    def export_symbols(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "plugin-manifest.json").write_text(
            self.manifest.model_dump_json(indent=2) + "\n"
        )
        for repo_id, spool in self._symbol_spools.items():
            spool.seek(0)
            with (directory / (repo_id + ".jsonl")).open("w") as output:
                for line in spool:
                    output.write(line)

    def close(self) -> None:
        for spool in self._symbol_spools.values():
            spool.close()
        self._symbol_spools.clear()
        self._repo_roots.clear()
