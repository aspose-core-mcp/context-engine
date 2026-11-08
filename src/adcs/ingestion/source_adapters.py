"""Source adapter contracts used by ingestion services."""

from dataclasses import dataclass
from enum import StrEnum


class SourceAdapterType(StrEnum):
    """Supported source adapter backends."""

    GIT = "git"
    FILESYSTEM = "filesystem"


@dataclass(slots=True, frozen=True)
class SourceConfig:
    """Adapter-agnostic source configuration model."""

    adapter: SourceAdapterType
    product: str
    language: str
    version: str
    path: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
