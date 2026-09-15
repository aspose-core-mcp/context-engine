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


def test_detect_layout_finds_nested_locale(tmp_path, monkeypatch):
    base = tmp_path / "Aspose.Slides" / "content"
    for sdk in ("net", "cpp"):
        for loc in ("english", "chinese"):
            d = base / sdk / loc / "aspose.slides"
            d.mkdir(parents=True, exist_ok=True)
            (d / "_index.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(det, "ROOT_DIR", tmp_path)
    repo = {"repo_id": "aspose.slides.apiref", "source_kind": "apiref",
            "git": {"submodule_path": "Aspose.Slides"}}
    result = det.detect_layout(repo)
    semantics = [d["semantic"] for d in result["dimensions"]]
    assert "doc_locale" in semantics
    assert semantics.index("programming_language") < semantics.index("doc_locale")
