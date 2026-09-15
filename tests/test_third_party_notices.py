from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "licenses" / "python_third_party_notices.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("python_third_party_notices", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notices_cover_installed_third_party_packages() -> None:
    text = _load_script().render_notices()

    assert text.startswith("Third-party software notices")
    assert "\nfastapi " in text
    assert "\npydantic " in text
    assert "License: " in text
    # The project itself is not a third-party package.
    assert "\nadcs " not in text


def test_notices_include_license_file_contents() -> None:
    text = _load_script().render_notices()

    fastapi_section = text.split("\nfastapi ", 1)[1].split("\n\n\n", 1)[0]
    assert "--- " in fastapi_section
    assert "Permission is hereby granted" in fastapi_section
