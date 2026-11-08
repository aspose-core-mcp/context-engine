"""Scoped, conservative recovery for non-canonical API symbol names."""

from __future__ import annotations

from dataclasses import dataclass

from adcs.indexing.apiref_symbol_store import ApiRefScope, ApiRefSymbol, ApiRefSymbolStore
from adcs.retrieval.profiles import symbol_allowed

_POOL_LIMIT = 101
_TYPE_KINDS = {"class", "interface", "struct", "enum", "enumeration", "delegate"}


@dataclass(frozen=True)
class SymbolCandidates:
    symbols: tuple[ApiRefSymbol, ...] = ()
    truncated: bool = False

    @property
    def unique_fqn(self) -> str | None:
        if len(self.symbols) == 1 and not self.truncated:
            return self.symbols[0].member_fqn
        return None

    def suggestions(self) -> list[dict[str, str]]:
        return [
            {
                "symbol_fqn": s.member_fqn,
                "kind": s.kind,
                "match_reason": "unique_short_name_match"
                if self.unique_fqn
                else "short_name_match",
            }
            for s in self.symbols[:10]
        ]


def find_symbol_candidates(
    *,
    store: ApiRefSymbolStore,
    scope: ApiRefScope,
    requested: str,
) -> SymbolCandidates:
    norm = requested.strip().strip(".").casefold()
    if not norm or not symbol_allowed(scope.product, scope.language, requested):
        return SymbolCandidates()
    leaf = norm.rsplit(".", 1)[-1]
    rows = store.search_symbols(pattern=leaf, scope=scope, limit=_POOL_LIMIT)
    candidates: dict[str, ApiRefSymbol] = {}
    for row in rows:
        if (row.product, row.language, row.version, row.locale) != (
            scope.product,
            scope.language,
            scope.version,
            scope.locale,
        ) or not symbol_allowed(scope.product, scope.language, row.member_fqn):
            continue
        if row.name.casefold() == leaf:
            candidates.setdefault(row.member_fqn.casefold(), row)
    values = sorted(candidates.values(), key=lambda s: s.member_fqn)
    suffixes = [
        s
        for s in values
        if s.member_fqn.casefold() == norm or s.member_fqn.casefold().endswith("." + norm)
    ]
    # A class and its constructor share a leaf; prefer actual type declarations.
    values = suffixes or values
    types = [s for s in values if s.kind in _TYPE_KINDS]
    return SymbolCandidates(tuple(types or values), len(rows) >= _POOL_LIMIT)


class SymbolNotFoundError(LookupError):
    def __init__(self, requested: str, candidates: SymbolCandidates) -> None:
        message = f"Symbol `{requested}` was not found."
        if candidates.unique_fqn and len(message) + len(candidates.unique_fqn) < 260:
            message += f" Try `{candidates.unique_fqn}`."
        else:
            message += " Use search_symbols to find its canonical name."
        super().__init__(message)
        self.details: dict[str, object] = {
            "requested_symbol": requested,
            "suggested_symbols": candidates.suggestions(),
        }
