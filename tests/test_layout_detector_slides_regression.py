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


def test_slides_layout_v2(tmp_path, monkeypatch):
    base = tmp_path / "Aspose.Slides" / "content"
    for sdk in ("net", "cpp", "java", "androidjava", "python-net"):
        for loc in ("english", "chinese", "french", "german", "russian", "spanish"):
            d = base / sdk / loc / "aspose.slides.charts"
            d.mkdir(parents=True, exist_ok=True)
            (d / "_index.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(det, "ROOT_DIR", tmp_path)
    res = det.detect_layout({"repo_id": "aspose.slides.apiref", "source_kind": "apiref",
                             "git": {"submodule_path": "Aspose.Slides"}})
    sem = [d["semantic"] for d in res["dimensions"]]
    assert sem == ["content_group", "programming_language", "doc_locale", "namespace"]
    assert res["uncertain"] is False
    assert res["confidence"] >= 0.8
