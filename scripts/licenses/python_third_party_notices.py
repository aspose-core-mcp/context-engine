#!/usr/bin/env python3
"""Collect the license texts of the installed Python packages into one notices file.

Container builds run this after installing the pinned dependency closure, so every image
ships the license terms of the third-party packages it redistributes. It reads package
metadata only and needs nothing beyond the standard library.

Usage:
    python scripts/licenses/python_third_party_notices.py --output THIRD_PARTY_NOTICES.txt
"""

from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

_PROJECT_DISTRIBUTIONS = frozenset({"adcs"})
_LICENSE_FILE_HINTS = ("license", "licence", "copying", "notice")
_HEADER = """\
Third-party software notices
============================

This image contains the Python packages listed below. Each entry gives the package
version, its declared license and the license files shipped with the package. The ADCS
code itself is MIT-licensed:
https://github.com/aspose-mcp/aspose-context-engine/blob/main/LICENSE
"""


def _declared_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    classifiers = [
        value.split("::")[-1].strip()
        for value in meta.get_all("Classifier") or []
        if value.startswith("License ::")
    ]
    if classifiers:
        return ", ".join(classifiers)
    raw = (meta.get("License") or "").strip()
    return raw.splitlines()[0][:200] if raw else "not declared"


def _license_files(dist: metadata.Distribution) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for entry in dist.files or []:
        parts = [part.lower() for part in entry.parts]
        in_metadata_dir = any(part.endswith((".dist-info", ".egg-info")) for part in parts)
        named_like_license = any(hint in entry.name.lower() for hint in _LICENSE_FILE_HINTS)
        if not in_metadata_dir or not (named_like_license or "licenses" in parts):
            continue
        path = Path(str(entry.locate()))
        if path.is_file():
            found.append((str(entry), path.read_text(encoding="utf-8", errors="replace")))
    return found


def render_notices() -> str:
    """Return the notices text for every third-party distribution in this environment."""
    distributions: dict[str, metadata.Distribution] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name and name.lower() not in _PROJECT_DISTRIBUTIONS:
            distributions.setdefault(name.lower(), dist)

    sections = [_HEADER]
    for key in sorted(distributions):
        dist = distributions[key]
        title = f"{dist.metadata['Name']} {dist.version}"
        lines = [title, "-" * len(title), f"License: {_declared_license(dist)}"]
        files = _license_files(dist)
        if not files:
            lines.append("No license file is included in the package metadata.")
        for relative_path, text in files:
            lines.extend(["", f"--- {relative_path} ---", text.rstrip()])
        sections.append("\n".join(lines))
    return "\n\n\n".join(sections) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, help="Write to this file instead of stdout.")
    args = parser.parse_args()
    text = render_notices()
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
