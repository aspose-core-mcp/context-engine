"""Server-selected scope for product-specific MCP endpoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MCPProductScope:
    product_id: str
    language: str
    title: str
    product_aliases: frozenset[str]
    language_aliases: frozenset[str]

    def apply(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Supply omitted scope and reject overrides before any retrieval runs."""
        scoped = dict(arguments)
        for field, expected, aliases in (
            ("product_id", self.product_id, self.product_aliases),
            ("language", self.language, self.language_aliases),
        ):
            value = scoped.get(field)
            if value is not None and (
                not isinstance(value, str) or value.strip().casefold() not in aliases
            ):
                raise ValueError(f"This endpoint requires {field}={expected!r}.")
            scoped[field] = expected
        return scoped


WORDS_NET_SCOPE = MCPProductScope(
    product_id="aspose.words",
    language="net",
    title="Aspose.Words for .NET",
    product_aliases=frozenset({"aspose.words", "words", "aspose words"}),
    language_aliases=frozenset(
        {
            "net",
            ".net",
            "dotnet",
            "c#",
            "csharp",
            "cs",
            "netcore",
            "net-core",
            "net core",
        }
    ),
)


TEX_NET_SCOPE = MCPProductScope(
    product_id="aspose.tex",
    language="net",
    title="Aspose.TeX for .NET",
    product_aliases=frozenset({"aspose.tex", "tex", "aspose tex"}),
    language_aliases=WORDS_NET_SCOPE.language_aliases,
)


@dataclass(frozen=True, slots=True)
class MCPProductGroup:
    """An endpoint grouping; its identity is never sent to retrieval stores."""

    product_id: str
    language: str
    title: str
    members: tuple[MCPProductScope, ...]

    def select(self, arguments: dict[str, Any]) -> tuple[MCPProductScope, ...]:
        product = arguments.get("product_id")
        selected = self.members
        if product is not None:
            selected = tuple(
                member
                for member in self.members
                if isinstance(product, str) and product.strip().casefold() in member.product_aliases
            )
            if not selected:
                raise ValueError("This endpoint allows only " + " and ".join(
                    member.product_id for member in self.members
                ) + ".")
        # Validate language even for resolve_product and empty data partitions.
        for member in selected:
            member.apply({**arguments, "product_id": member.product_id})
        return selected


TOTAL_NET_SCOPE = MCPProductGroup(
    product_id="aspose.total",
    language="net",
    title="Aspose.Total for .NET (Words and TeX)",
    members=(WORDS_NET_SCOPE, TEX_NET_SCOPE),
)


# Opt-in catalog-driven serving; legacy images need not contain extractor packages.
_catalog_path = os.environ.get("ADCS_PRODUCT_PLUGIN_CATALOG")
if _catalog_path:
    from adcs.plugins.catalog import PluginCatalog

    _catalog = PluginCatalog(_catalog_path)
    _composition = _catalog.compositions.get("aspose.total.net")
    if _composition is not None and _composition.language != "net":
        raise ValueError("The Total/.NET endpoint requires a .NET composition")
    _members = []
    for _plugin_id in (_composition.members if _composition is not None else []):
        _plugin = _catalog.extractor(_plugin_id)
        _name = _plugin.product_id.removeprefix("aspose.")
        _members.append(
            MCPProductScope(
                product_id=_plugin.product_id,
                language=_plugin.language,
                title=_plugin.title,
                product_aliases=frozenset({_plugin.product_id, _name, f"aspose {_name}"}),
                language_aliases=WORDS_NET_SCOPE.language_aliases,
            )
        )
    TOTAL_NET_SCOPE = MCPProductGroup(
        product_id="aspose.total",
        language="net",
        title="Aspose.Total for .NET",
        members=tuple(_members),
    )
