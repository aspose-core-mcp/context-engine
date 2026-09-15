from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

PROMPT_PACK_DIR = Path(__file__).resolve().parents[1] / "prompts" / "hugo_conversion"
MANIFEST_PATH = PROMPT_PACK_DIR / "MANIFEST.yaml"


def _load_manifest() -> dict:
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_lists_every_prompt_file() -> None:
    manifest = _load_manifest()
    declared = {entry["filename"] for entry in manifest["prompts"]}
    on_disk = {
        p.name
        for p in PROMPT_PACK_DIR.iterdir()
        if p.is_file() and p.name not in {"MANIFEST.yaml", "README.md"}
    }
    missing_from_manifest = on_disk - declared
    missing_on_disk = declared - on_disk
    assert not missing_from_manifest, (
        f"Prompt files present on disk but missing from MANIFEST.yaml: "
        f"{sorted(missing_from_manifest)}. "
        f"Add a manifest entry with version, sha256, and a change_history record."
    )
    assert not missing_on_disk, (
        f"MANIFEST.yaml lists files not present on disk: {sorted(missing_on_disk)}. "
        f"Either remove the manifest entry or restore the file."
    )


@pytest.mark.parametrize(
    "entry",
    _load_manifest()["prompts"],
    ids=lambda entry: entry["filename"],
)
def test_prompt_file_sha256_matches_manifest(entry: dict) -> None:
    filename = entry["filename"]
    declared = entry["sha256"]
    actual = _sha256_of(PROMPT_PACK_DIR / filename)
    assert actual == declared, (
        f"Hash drift detected for prompts/hugo_conversion/{filename}.\n"
        f"  Manifest:  {declared}\n"
        f"  On disk:   {actual}\n"
        f"If this change is intentional, do ONE of:\n"
        f"  (a) Add a new versioned file (e.g. {filename.replace('.v1.', '.v2.')}) "
        f"with a new MANIFEST.yaml entry, OR\n"
        f"  (b) Bump `version` on the existing entry and append a "
        f"`change_history` record explaining the change."
    )


def test_manifest_change_history_is_well_formed() -> None:
    manifest = _load_manifest()
    for entry in manifest["prompts"]:
        history = entry["change_history"]
        assert history, f"{entry['filename']} has empty change_history"
        for record in history:
            assert {"version", "date", "author", "change", "rationale"}.issubset(record), (
                f"{entry['filename']} change_history entry missing required keys "
                f"(version, date, author, change, rationale): {record}"
            )
        latest_version = history[-1]["version"]
        assert latest_version == entry["version"], (
            f"{entry['filename']}: top-level version ({entry['version']!r}) "
            f"must match the latest change_history version ({latest_version!r})"
        )
