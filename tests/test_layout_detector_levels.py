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


def test_summarize_levels_n_returns_value_set_per_level():
    vectors = [
        ("content", "net", "english", "aspose.slides"),
        ("content", "net", "chinese", "aspose.slides.charts"),
        ("content", "cpp", "english", "aspose.slides"),
    ]
    levels = det.summarize_levels_n(vectors, max_depth=4)
    assert levels[0] == {"content"}
    assert levels[1] == {"net", "cpp"}
    assert levels[2] == {"english", "chinese"}
    assert levels[3] == {"aspose.slides", "aspose.slides.charts"}
