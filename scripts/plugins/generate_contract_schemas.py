"""Regenerate versioned plugin schemas from the host's compatibility models."""

import json
from pathlib import Path

from adcs.plugins.catalog import PluginManifest
from adcs.plugins.contracts import ExtractionFailure, ExtractionResponse

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "contracts/plugin-extraction/v1"
DIRECTORY.mkdir(parents=True, exist_ok=True)
for name, model in (
    ("response", ExtractionResponse),
    ("failure", ExtractionFailure),
    ("manifest", PluginManifest),
):
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    (DIRECTORY / (name + ".schema.json")).write_text(json.dumps(schema, indent=2) + "\n")
