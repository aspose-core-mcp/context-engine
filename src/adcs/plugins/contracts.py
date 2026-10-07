"""Published v1 wire models; plugins may implement them in any language."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from adcs.indexing.apiref_symbol_store import ApiRefSymbol
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.hugo_parser import HugoNormalizedPage
from adcs.ingestion.normalized_document import NormalizedDocument


class ExtractedContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: HugoNormalizedPage
    normalized_document: NormalizedDocument
    chunk_records: list[StageDChunkRecord] = Field(min_length=1)
    symbols: list[ApiRefSymbol]


class DiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[str] = Field(min_length=1)


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: Literal["adcs.extraction.v1"]
    plugin_id: str
    plugin_version: str
    result: ExtractedContent | DiscoveryResult


class ExtractionFailure(BaseModel):
    contract: Literal["adcs.extraction.v1"]
    plugin_id: str
    plugin_version: str
    error: dict[str, str]
