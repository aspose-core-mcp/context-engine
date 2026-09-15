import importlib.util
import sys
from pathlib import Path

_script = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "sources"
    / "layout"
    / "detect_source_layouts.py"
)
_spec = importlib.util.spec_from_file_location("detect_source_layouts", _script)
det = importlib.util.module_from_spec(_spec)
sys.modules["detect_source_layouts"] = det
_spec.loader.exec_module(det)


def _semantics(vectors):
    levels = det.summarize_levels_n(vectors)
    schema = det.assemble_schema(levels)
    return [d["semantic"] for d in schema["dimensions"]], schema


def test_slides_programming_then_locale_then_namespace():
    vectors = [
        ("content", "net", "english", "aspose.slides"),
        ("content", "net", "chinese", "aspose.slides"),
        ("content", "cpp", "english", "aspose.slides.charts"),
    ]
    semantics, schema = _semantics(vectors)
    assert semantics == ["content_group", "programming_language", "doc_locale", "namespace"]
    assert schema["uncertain"] is False


def test_locale_first_layout():
    vectors = [("english", "net", "aspose.x"), ("chinese", "net", "aspose.x")]
    semantics, _ = _semantics(vectors)
    assert semantics == ["doc_locale", "programming_language", "namespace"]


def test_version_dimension_detected():
    vectors = [("net", "latest-stable", "english", "aspose.x")]
    semantics, _ = _semantics(vectors)
    assert semantics == ["programming_language", "version", "doc_locale", "namespace"]
