#!/usr/bin/env python3
"""Static cost-surface analyzer for ADCS LLM call sites.

Counts LLM API call sites per module via AST inspection. Output is a JSON
report consumable by ``enforce_perf_budgets.py``.

The intent is to catch silent fan-out: a PR adding 10 new LLM calls inside a
hot retrieval path should be visible to reviewers as a budget breach, not as
"+5 lines of innocuous code". This is dynamic enough to track real changes
but static enough to run in every PR without a database / corpus.

Heuristic — a "call site" is any function call where the receiver matches one
of the known LLM client identifiers (``chat.completions.create``,
``embeddings.create``, ``LLMClient.score_chunk``, etc.) or where the call's
attribute path ends in a known LLM verb (``embed``, ``score_chunk``,
``classify``, etc.). Signal is approximate but stable; we adjust budgets in
``config/perf/budgets.yaml`` whenever the surface intentionally grows.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "reports" / "quality-gates" / "cost-summary.json"

# These are the receiver-attribute paths and bare function names that we count
# as "an LLM call site". Conservative defaults — extend as new clients appear.
LLM_CLIENT_VERBS = frozenset(
    {
        # OpenAI-compatible Python SDK
        "chat.completions.create",
        "completions.create",
        "embeddings.create",
        "responses.create",
        # Anthropic Python SDK
        "messages.create",
        "completions.create",
        # Generic ADCS abstraction (planned)
        "score_chunk",
        "score_with_voting",
        "embed",
        "embed_batch",
        "classify",
        "detect_locale",
        "translate",
        "reverse_translate",
        # llama.cpp / vLLM / Ollama clients
        "generate",
        "chat",
    }
)

# Modules that should never be counted (test stubs, mock helpers).
SKIP_PATTERNS = (
    "tests/",
    "scripts/",
    "_test_helpers/",
)


def _attribute_path(node: ast.AST) -> str:
    """Return the dotted path of an Attribute/Name node, e.g. 'a.b.c'."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _matches_llm_verb(attribute_path: str) -> bool:
    """Match a verb against the known set, looking at any trailing suffix."""
    if not attribute_path:
        return False
    # Direct full-path match, e.g. 'self.client.embeddings.create' has suffix
    # 'embeddings.create'.
    parts = attribute_path.split(".")
    for i in range(len(parts)):
        candidate = ".".join(parts[i:])
        if candidate in LLM_CLIENT_VERBS:
            return True
    # Bare verb match — e.g. 'await score_chunk(...)' parses as Name not Attr.
    return parts[-1] in LLM_CLIENT_VERBS


def _count_in_file(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            attr_path = _attribute_path(node.func)
            if _matches_llm_verb(attr_path):
                count += 1
    return count


def _iter_source_files(root: Path) -> list[Path]:
    src_root = root / "src"
    if not src_root.exists():
        return []
    files: list[Path] = []
    for path in src_root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(p) for p in SKIP_PATTERNS):
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help="Where to write the cost summary JSON.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the summary to stdout, do not write to disk.",
    )
    args = parser.parse_args()

    counter: Counter[str] = Counter()
    files = _iter_source_files(REPO_ROOT)
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        n = _count_in_file(path)
        if n > 0:
            counter[rel] = n

    overall = sum(counter.values())
    payload = {
        "generated_at": None,  # left None for deterministic diffs in CI; populate in CI job
        "overall_total": overall,
        "per_module": dict(sorted(counter.items())),
        "modules_scanned": len(files),
        "verbs_tracked": sorted(LLM_CLIENT_VERBS),
    }

    output_text = json.dumps(payload, indent=2, sort_keys=False)
    print(output_text)

    if not args.print_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n")
        print(f"\nWrote {args.output.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
