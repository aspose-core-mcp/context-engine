"""Run with stdlib unittest; no engine installation needed."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((PLUGIN / "plugin.json").read_text())


class ExtractionContractTest(unittest.TestCase):
    def test_docs_and_api_output(self):
        for kind in ("docs", "apiref"):
            with self.subTest(kind=kind):
                source = MANIFEST["sources"][kind]
                relative = source["prefix"] + "/_index.md"
                request = {
                    "contract": MANIFEST["contract"],
                    "plugin_id": MANIFEST["plugin_id"],
                    "product_id": MANIFEST["product_id"],
                    "language": MANIFEST["language"],
                    "operation": "extract",
                    "source_kind": kind,
                    "repo_id": source["repo_id"],
                    "product_family": "aspose",
                    "source_path": relative,
                    "relative_repo_path": relative,
                    "layout_detection": source["layout"],
                    "source_revision": "fixture",
                    "canonical_base_url": source["canonical_base_url"],
                    "raw_markdown": (PLUGIN / "tests/fixtures" / (kind + ".md")).read_text(),
                }
                result = subprocess.run(
                    [sys.executable, "-I", str(PLUGIN / "worker.py")],
                    input=json.dumps(request),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                response = json.loads(result.stdout)["result"]
                self.assertEqual(
                    response["normalized_document"]["document"]["product_id"],
                    MANIFEST["product_id"],
                )
                self.assertTrue(response["chunk_records"])
                self.assertTrue(response["page"]["code_blocks"])
                if kind == "apiref":
                    self.assertTrue(response["symbols"])


if __name__ == "__main__":
    unittest.main()
