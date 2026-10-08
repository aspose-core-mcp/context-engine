"""Offline tests for the shortcode format used by the Word-to-PDF guide."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adcs_words_net import docs_extractor, gist_examples, worker

GIST_ID = "0b968ac8900f80c11e109dffb105f3da"
FILENAME = "Examples-CSharp-Loading-and-Saving-Doc2Pdf-Doc2Pdf.cs"
SHORTCODE = '{{< gist "aspose-com-gists" "' + GIST_ID + '" "' + FILENAME + '" >}}'
CODE = 'var doc = new Document("input.docx");\ndoc.Save("output.pdf");'


class GistExamplesTest(unittest.TestCase):
    def test_real_declarations_and_overloads(self):
        plugin = Path(__file__).resolve().parents[1]
        manifest = json.loads((plugin / "plugin.json").read_text())
        source = manifest["sources"]["apiref"]
        for fixture, tail in (
            ("save", "aspose.words/document/save"),
            ("lines", "aspose.words.properties/builtindocumentproperties/lines"),
        ):
            relative = "english/net/" + tail + "/_index.md"
            result = worker.handle({
                "contract": manifest["contract"], "plugin_id": manifest["plugin_id"],
                "product_id": manifest["product_id"], "language": "net", "operation": "extract",
                "source_kind": "apiref", "repo_id": source["repo_id"],
                "product_family": "aspose", "source_path": source["path"] + "/" + relative,
                "relative_repo_path": relative, "source_prefix": source["prefix"],
                "layout_detection": source["layout"], "source_revision": "fixture",
                "canonical_base_url": source["canonical_base_url"],
                "raw_markdown": (plugin / "tests/fixtures" / (fixture + "-real.md")).read_text(),
            })
            symbols = result["symbols"]
            if fixture == "save":
                self.assertGreater(len(symbols), 1)
                self.assertEqual(len({s["signature"] for s in symbols}), len(symbols))
                self.assertTrue(all(
                    s["member_fqn"] == "Aspose.Words.Document.Save" for s in symbols
                ))
                self.assertTrue(all(s["signature"].startswith("public ") for s in symbols))
                self.assertTrue(any("SaveFormat saveFormat" in s["signature"] for s in symbols))
                self.assertTrue(all(
                    s["payload"]["section_anchor"].startswith("#save") for s in symbols
                ))
            else:
                self.assertEqual(symbols[0]["signature"], "public int Lines { get; set; }")
            self.assertTrue(all("Assert.That" not in (s["signature"] or "") for s in symbols))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.cache = self.root / "examples.json"
        self.entry = {
            "revision": "a" * 40, "code": CODE,
            "sha256": hashlib.sha256(CODE.encode()).hexdigest(),
        }
        self.cache.write_text(json.dumps({
            "schema": 1, "examples": {f"aspose-com-gists/{GIST_ID}/{FILENAME}": self.entry},
        }))

    def test_pdf_shortcode_becomes_csharp_code_block(self):
        text = "# Convert to PDF\n\n" + SHORTCODE + "\n\nFollowing prose."
        with patch.object(docs_extractor, "expand", side_effect=lambda t: gist_examples.expand(
            t, cache_path=self.cache
        )):
            page = docs_extractor.extract({
                "repo_id": "aspose.words.net.docs", "source_path": "sources/docs/net/pdf.md",
                "source_kind": "docs", "product_id": "aspose.words", "product_family": "aspose",
                "relative_repo_path": "net/pdf.md",
                "layout_detection": {"layout_type": "programming_language/content"},
                "raw_markdown": text,
            })
        self.assertEqual(len(page.code_blocks), 1)
        self.assertEqual(page.code_blocks[0].language, "csharp")
        self.assertEqual(page.code_blocks[0].code, CODE)
        self.assertFalse(page.parse_warnings)

    def test_gist_code_reaches_retrieval_snippets_with_page_citation(self):
        with patch.object(docs_extractor, "expand", side_effect=lambda t: gist_examples.expand(
            t, cache_path=self.cache
        )):
            result = worker.handle({
                "contract": "adcs.extraction.v1", "plugin_id": "aspose.words.net",
                "product_id": "aspose.words", "language": "net", "operation": "extract",
                "source_kind": "docs", "repo_id": "aspose.words.net.docs",
                "product_family": "aspose", "source_path": "sources/docs/net/pdf.md",
                "relative_repo_path": "net/pdf.md", "source_prefix": "net",
                "layout_detection": {"layout_type": "programming_language/content"},
                "source_revision": "fixture", "canonical_base_url": "https://docs.aspose.com/words/net",
                "raw_markdown": "# Convert to PDF\n" + SHORTCODE,
            })
        snippets = [s for c in result["chunk_records"] for s in c["executable_snippets"]]
        self.assertEqual(len(snippets), 1)
        self.assertEqual(snippets[0]["code"], CODE)
        self.assertEqual(snippets[0]["language"], "csharp")
        self.assertEqual(
            snippets[0]["parent_canonical_url"], "https://docs.aspose.com/words/net/pdf/"
        )

    def test_missing_and_corrupt_cache_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError, "Missing Gist"):
            gist_examples.expand(SHORTCODE, cache_path=self.root / "missing.json")
        data = json.loads(self.cache.read_text())
        next(iter(data["examples"].values()))["code"] = "changed"
        self.cache.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "checksum"):
            gist_examples.expand(SHORTCODE, cache_path=self.cache)

    def test_prepare_reuses_pinned_cache_without_network(self):
        (self.root / "page.md").write_text(SHORTCODE)
        with patch.object(gist_examples.subprocess, "run") as run:
            result = gist_examples.prepare(self.root, self.cache)
        run.assert_not_called()
        self.assertEqual(result["downloaded"], 0)

    def test_prepare_records_revision_and_reuses_duplicate_reference(self):
        (self.root / "page.md").write_text(SHORTCODE + "\n" + SHORTCODE)
        with patch.object(gist_examples.subprocess, "run") as run, patch.object(
            gist_examples.subprocess, "check_output", side_effect=["b" * 40 + "\n", CODE.encode()]
        ):
            result = gist_examples.prepare(self.root, self.cache, refresh=True)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result["references"], 1)
        entry = next(iter(json.loads(self.cache.read_text())["examples"].values()))
        self.assertEqual(entry["revision"], "b" * 40)
        self.assertEqual(gist_examples.checked_code(entry), CODE)

    def test_failed_download_preserves_previous_cache(self):
        original = self.cache.read_bytes()
        (self.root / "page.md").write_text(SHORTCODE)
        with patch.object(gist_examples.subprocess, "run", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                gist_examples.prepare(self.root, self.cache, refresh=True)
        self.assertEqual(self.cache.read_bytes(), original)

    def test_rejects_ambiguous_reference(self):
        with self.assertRaises(ValueError):
            list(gist_examples.references('{{< gist "owner" "abcd" >}}'))


if __name__ == "__main__":
    unittest.main()
