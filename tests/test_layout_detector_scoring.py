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


def test_score_level_classifies_each_slides_level():
    assert det.score_level({"content"}) == {
        "doc_locale": 0.0, "programming_language": 0.0, "version": 0.0
    }
    sdk = det.score_level({"net", "cpp", "java", "python-net"})
    assert sdk["programming_language"] == 1.0
    loc = det.score_level({"english", "chinese", "french", "german", "russian", "spanish"})
    assert loc["doc_locale"] == 1.0
    ver = det.score_level({"latest-stable"})
    assert ver["version"] == 1.0
