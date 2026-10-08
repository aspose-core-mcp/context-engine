"""Declarative product/platform retrieval policy; never executes plugin code."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


def words(value: str) -> set[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


class RetrievalRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule_id: str = Field(min_length=1)
    all_terms: list[str] = Field(min_length=1, max_length=12)
    any_terms: list[str] = Field(default_factory=list, max_length=12)
    any_phrases: list[str] = Field(default_factory=list, max_length=12)
    exclude_terms: list[str] = Field(default_factory=list, max_length=30)
    preferred_symbols: list[str] = Field(min_length=1, max_length=4)

    def matches(self, query: str) -> bool:
        tokens = words(query)
        # Explicit qualified types/members always take precedence over policy.
        if re.search(r"\b\w+(?:\.\w+){2,}\b", query):
            return False
        normalized = " " + " ".join(re.findall(r"[a-z0-9]+", query.casefold())) + " "
        if self.any_terms and not any(words(term) <= tokens for term in self.any_terms):
            return False
        if self.any_phrases and not any(
            " " + " ".join(re.findall(r"[a-z0-9]+", phrase.casefold())) + " " in normalized
            for phrase in self.any_phrases
        ):
            return False
        return all(words(term) <= tokens for term in self.all_terms) and not any(
            words(term) <= tokens for term in self.exclude_terms
        )


class RetrievalProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    profile_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    excluded_namespaces: list[str] = Field(default_factory=list, max_length=50)
    rules: list[RetrievalRule] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_rules(self) -> RetrievalProfile:
        for namespace in self.excluded_namespaces:
            if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", namespace):
                raise ValueError("Excluded namespaces must be qualified identifiers")
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate retrieval rule ID")
        for rule in self.rules:
            for term in [*rule.all_terms, *rule.any_terms, *rule.any_phrases, *rule.exclude_terms]:
                if not words(term):
                    raise ValueError("Retrieval terms must contain words")
            for symbol in rule.preferred_symbols:
                if not self.allows(symbol):
                    raise ValueError("Preferred symbol conflicts with excluded namespace")
                if not symbol.casefold().startswith(self.product_id.casefold() + "."):
                    raise ValueError("Preferred symbol is outside profile product")
        return self

    def allows(self, member_fqn: str) -> bool:
        candidate = member_fqn.casefold()
        return not any(candidate == ns.casefold() or candidate.startswith(ns.casefold() + ".")
                       for ns in self.excluded_namespaces)

    def targets(self, query: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            symbol for rule in self.rules if rule.matches(query)
            for symbol in rule.preferred_symbols
        ))[:8]

    def explain(self, query: str) -> dict[str, object]:
        return {"profile_id": self.profile_id, "version": self.version,
                "excluded_namespaces": list(self.excluded_namespaces),
                "matched_rules": [r.rule_id for r in self.rules if r.matches(query)],
                "preferred_symbols": list(self.targets(query))}


@lru_cache(maxsize=8)
def load_profiles(catalog_path: str) -> dict[tuple[str, str], RetrievalProfile]:
    from adcs.plugins.catalog import PluginCatalog

    catalog = PluginCatalog(catalog_path)
    profiles = {}
    for plugin_id, manifest in catalog.plugins.items():
        if manifest.retrieval_profile is None:
            continue
        root = catalog.directories[plugin_id]
        path = (root / manifest.retrieval_profile).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Retrieval profile escapes plugin directory")
        profile = RetrievalProfile.model_validate_json(path.read_text())
        scope = (manifest.product_id, manifest.language)
        if (profile.product_id, profile.language) != scope:
            raise ValueError("Retrieval profile scope differs from plugin")
        if scope in profiles:
            raise ValueError("Duplicate retrieval profile scope")
        profiles[scope] = profile
    return profiles


def profile_for(product: str, language: str) -> RetrievalProfile | None:
    configured = os.environ.get("ADCS_RETRIEVAL_PLUGIN_CATALOG")
    path = Path(configured) if configured else (
        Path(__file__).resolve().parents[3] / "config/product-platform-plugins.json"
    )
    # Standalone engine installations need not ship the evaluation plugins.
    if not configured and not path.exists():
        return None
    return load_profiles(str(path.resolve())).get((product, language))


def symbol_allowed(product: str, language: str, member_fqn: str | None) -> bool:
    profile = profile_for(product, language)
    return not profile or not member_fqn or profile.allows(member_fqn)


def candidate_allowed(metadata) -> bool:
    # Documentation eligibility is deliberately unchanged. Legacy namespace
    # pages can lack symbol_fqn, so also recognize canonical namespace segments.
    if metadata.source_kind != "apiref":
        return True
    if not symbol_allowed(metadata.product_id, metadata.programming_language, metadata.symbol_fqn):
        return False
    if metadata.symbol_fqn:
        return True
    segments = unquote(urlsplit(metadata.canonical_url).path).split("/")
    return all(symbol_allowed(metadata.product_id, metadata.programming_language, segment)
               for segment in segments if segment)


class EligibleSymbolStore:
    """Defense at the shared serving boundary, including injected/custom stores.

    Built-in stores filter before limits. Custom stores retain their own pool
    limits, so filtering their returned rows can produce fewer eligible results.
    """

    def __init__(self, store):
        self._store = store

    def __getattr__(self, name):
        method = getattr(self._store, name)
        if name not in {
            "get_symbol", "list_members", "list_overloads", "search_symbols", "fts_search"
        }:
            return method

        def eligible(**kwargs):
            scope = kwargs["scope"]
            requested = kwargs.get("member_fqn", kwargs.get("parent_fqn"))
            if not symbol_allowed(scope.product, scope.language, requested):
                return ()
            return tuple(row for row in method(**kwargs)
                         if symbol_allowed(scope.product, scope.language, row.member_fqn))
        return eligible
