"""Pinned, offline Gist examples owned by the Words documentation plugin.

Run this module explicitly to populate the cache; extraction never fetches URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = PLUGIN_ROOT / "sources/gist-examples.json"
GIST = re.compile(r"{{(?P<open>[<%])\s*gist\b(?P<args>.*?)\s*(?P<close>[>%])}}", re.S)


def references(text: str):
    for match in GIST.finditer(text):
        args = shlex.split(match["args"])
        if (
            (match["open"], match["close"]) not in {("<", ">"), ("%", "%")}
            or len(args) != 3
            or not re.fullmatch(r"[\w-]+", args[0])
            or not re.fullmatch(r"[a-fA-F0-9]+", args[1])
            or not args[2] or "/" in args[2] or "\\" in args[2]
            or args[2] in {".", ".."}
        ):
            raise ValueError("Gist examples require an owner, hexadecimal ID and filename")
        yield match, tuple(args)


def key(reference: tuple[str, str, str]) -> str:
    return "/".join(reference)


def read_cache(path: Path) -> dict:
    if not path.exists():
        return {"schema": 1, "examples": {}}
    cache = json.loads(path.read_text())
    if cache.get("schema") != 1 or not isinstance(cache.get("examples"), dict):
        raise ValueError("Invalid Words Gist example cache")
    return cache


def checked_code(entry: dict) -> str:
    code = entry["code"]
    if (
        not isinstance(code, str) or not code.strip()
        or hashlib.sha256(code.encode()).hexdigest() != entry["sha256"]
        or not re.fullmatch(r"[a-fA-F0-9]{40}", entry["revision"])
    ):
        raise ValueError("Gist cache revision/content checksum validation failed")
    return code


def expand(text: str, *, cache_path: Path = DEFAULT_CACHE) -> str:
    matches = list(references(text))
    if not matches:
        return text
    cache = read_cache(cache_path)
    for match, reference in reversed(matches):
        entry = cache["examples"].get(key(reference))
        if entry is None:
            raise ValueError(
                f"Missing Gist example {key(reference)}; run gist_examples preparation"
            )
        code = checked_code(entry)
        extension = Path(reference[2]).suffix.lower()
        language = {".cs": "csharp", ".vb": "vbnet", ".json": "json"}.get(extension, "text")
        # The existing Markdown parser supports triple fences. Refuse embedded
        # closing fences instead of silently corrupting the surrounding content.
        if any(line.lstrip().startswith("```") for line in code.splitlines()):
            raise ValueError(f"Unsupported Markdown fence inside Gist {key(reference)}")
        replacement = f"\n```{language}\n{code.rstrip()}\n```\n"
        text = text[:match.start()] + replacement + text[match.end():]
    return text


def prepare(source_root: Path, cache_path: Path, *, refresh: bool = False) -> dict:
    if not source_root.is_dir():
        raise ValueError(f"Documentation source directory does not exist: {source_root}")
    refs = sorted({
        reference for path in source_root.rglob("*.md")
        for _, reference in references(path.read_text(encoding="utf-8-sig"))
    })
    if not refs:
        raise ValueError("No Gist examples found in the selected documentation source")
    cache = read_cache(cache_path)
    pending = []
    for reference in refs:
        existing = cache["examples"].get(key(reference))
        if existing is not None and not refresh:
            checked_code(existing)
        else:
            pending.append(reference)
    with TemporaryDirectory(prefix="words-gists-") as temporary:
        for gist_id in sorted({ref[1] for ref in pending}):
            checkout = Path(temporary) / gist_id
            subprocess.run(
                ["git", "clone", "--depth", "1", "https://gist.github.com/" + gist_id + ".git",
                 str(checkout)], check=True, timeout=180,
            )
            revision = subprocess.check_output(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True, timeout=30,
            ).strip()
            for reference in (ref for ref in pending if ref[1] == gist_id):
                code = subprocess.check_output(
                    ["git", "-C", str(checkout), "show", revision + ":" + reference[2]],
                    timeout=30,
                ).decode("utf-8-sig")
                entry = {
                    "revision": revision, "code": code,
                    "sha256": hashlib.sha256(code.encode()).hexdigest(),
                    "source_url": f"https://gist.github.com/{reference[0]}/{gist_id}/{revision}",
                }
                checked_code(entry)
                cache["examples"][key(reference)] = entry
    # Write only after every referenced file has been fetched and validated.
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")
    temporary_path.replace(cache_path)
    return {"references": len(refs), "downloaded": len(pending), "cache": str(cache_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root", type=Path, default=PLUGIN_ROOT / "sources/documentation/net"
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--refresh", action="store_true", help="Explicitly update pinned examples")
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_root, args.cache, refresh=args.refresh)))


if __name__ == "__main__":
    main()
