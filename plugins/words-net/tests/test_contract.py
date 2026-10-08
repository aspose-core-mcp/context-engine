"""Run with stdlib unittest; no engine installation needed."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((PLUGIN / "plugin.json").read_text())


class ExtractionContractTest(unittest.TestCase):
    def test_real_document_and_node_document_are_distinct_with_clean_examples(self):
        source = MANIFEST["sources"]["apiref"]
        cases = (
            ("document", "document", "Aspose.Words.Document", "public class Document"),
            ("node-document", "node/document", "Aspose.Words.Node.Document", "public virtual"),
        )
        for fixture, tail, expected_fqn, signature in cases:
            with self.subTest(fixture=fixture):
                relative = "english/net/aspose.words/" + tail + "/_index.md"
                request = {
                    "contract": MANIFEST["contract"], "plugin_id": MANIFEST["plugin_id"],
                    "product_id": MANIFEST["product_id"], "language": "net",
                    "operation": "extract", "source_kind": "apiref",
                    "repo_id": source["repo_id"], "product_family": "aspose",
                    "source_path": source["path"] + "/" + relative,
                    "relative_repo_path": relative, "source_prefix": source["prefix"],
                    "layout_detection": source["layout"], "source_revision": "fixture-sha",
                    "canonical_base_url": source["canonical_base_url"],
                    "raw_markdown": (
                        PLUGIN / "tests/fixtures" / (fixture + "-real.md")
                    ).read_text(),
                }
                result = subprocess.run(
                    [sys.executable, "-I", str(PLUGIN / "worker.py")],
                    input=json.dumps(request), capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                output = json.loads(result.stdout)["result"]
                symbol = output["symbols"][0]
                self.assertEqual(symbol["member_fqn"], expected_fqn)
                self.assertTrue(symbol["signature"].startswith(signature))
                self.assertTrue(symbol["canonical_url"].endswith("/" + tail + "/"))
                examples = symbol["payload"]["examples"]
                self.assertEqual(len(examples), 2 if fixture == "document" else 1)
                for example in examples:
                    self.assertNotIn("See Also", example)
                    self.assertNotIn("## Remarks", example)
                    self.assertNotIn(symbol["signature"], example)
                self.assertTrue(all(
                    s["language"] == "csharp" for s in symbol["payload"]["example_snippets"]
                ))

    def test_canonical_urls(self):
        for kind in ("docs", "apiref"):
            source = MANIFEST["sources"][kind]
            base = source["canonical_base_url"]
            origin = base.removesuffix("/words/net")
            cases = [
                ("_index.md", None, base + "/"),
                ("_index.md", "/net/", base + "/"),
                ("_index.md", "/net", base + "/"),
                ("guide/_index.md", "/net/guide/", base + "/guide/"),
                (
                    "guide/_index.md", "/net/guide/?view=net#example",
                    base + "/guide/?view=net#example",
                ),
                ("_index.md", "/net/?view=net#example", base + "/?view=net#example"),
                ("guide/_index.md", "/network/guide/", origin + "/network/guide/"),
                ("guide/_index.md", None, base + "/guide/"),
                ("guide/details.md", None, base + "/guide/details/"),
                ("guide/details.md", "", base + "/guide/details/"),
                ("guide/_index.md", "/words/net/guide/", base + "/guide/"),
                ("guide/_index.md", "guide/?view=net#example", base + "/guide/?view=net#example"),
                ("guide/_index.md", "/custom/", origin + "/custom/"),
                ("guide/_index.md", "https://example.com/explicit/", "https://example.com/explicit/"),
                ("guide/_index.md", "//example.com/guide/", None),
                ("guide/_index.md", "javascript:alert(1)", None),
            ]
            for path, override, expected in cases:
                with self.subTest(kind=kind, path=path, override=override):
                    relative = source["prefix"] + "/" + path
                    frontmatter = "title: Guide\nsymbol_kind: class\n"
                    if override is not None:
                        frontmatter += "url: " + json.dumps(override) + "\n"
                    request = {
                        "contract": MANIFEST["contract"],
                        "plugin_id": MANIFEST["plugin_id"],
                        "product_id": MANIFEST["product_id"],
                        "language": MANIFEST["language"],
                        "operation": "extract",
                        "source_kind": kind,
                        "repo_id": source["repo_id"],
                        "product_family": "aspose",
                        "source_path": source["path"] + "/" + relative,
                        "relative_repo_path": relative,
                        "source_prefix": source["prefix"],
                        "layout_detection": source["layout"],
                        "source_revision": "fixture",
                        "canonical_base_url": base,
                        "raw_markdown": "---\n" + frontmatter + "---\n# Guide\nUseful content.\n",
                    }
                    result = subprocess.run(
                        [sys.executable, "-I", str(PLUGIN / "worker.py")],
                        input=json.dumps(request), capture_output=True, text=True,
                    )
                    if expected is None:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("Canonical URL overrides", result.stdout)
                        continue
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    response = json.loads(result.stdout)["result"]
                    self.assertEqual(
                        response["normalized_document"]["document"]["canonical_url"], expected
                    )
                    for chunk in response["chunk_records"]:
                        self.assertEqual(chunk["canonical_url"], expected)
                        self.assertEqual(chunk["section_anchor"], "#")
                    for symbol in response["symbols"]:
                        self.assertEqual(symbol["canonical_url"], expected)

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

    def test_explicit_heading_anchor_is_shared_by_code_citations(self):
        source = MANIFEST["sources"]["docs"]
        request = {
            "contract": MANIFEST["contract"], "plugin_id": MANIFEST["plugin_id"],
            "product_id": MANIFEST["product_id"], "language": "net",
            "operation": "extract", "source_kind": "docs", "repo_id": source["repo_id"],
            "product_family": "aspose", "source_path": source["path"] + "/net/_index.md",
            "relative_repo_path": "net/_index.md", "source_prefix": "net",
            "layout_detection": source["layout"], "source_revision": "fixture",
            "canonical_base_url": source["canonical_base_url"],
            "raw_markdown": "# Examples {#examples}\n"
            + "```csharp\nvar doc = 1;\n```\n",
        }
        result = subprocess.run(
            [sys.executable, "-I", str(PLUGIN / "worker.py")],
            input=json.dumps(request), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        response = json.loads(result.stdout)["result"]
        self.assertTrue(any(c["executable_snippets"] for c in response["chunk_records"]))
        for chunk in response["chunk_records"]:
            self.assertEqual(chunk["section_anchor"], "#examples")
            for snippet in chunk["executable_snippets"]:
                self.assertEqual(snippet["parent_section_anchor"], "#examples")


if __name__ == "__main__":
    unittest.main()
