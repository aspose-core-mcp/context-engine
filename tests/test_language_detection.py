"""Tests for _detect_language_hint to prevent compound-language false positives."""

from __future__ import annotations

import pytest

from adcs.api.public_docs_query import _detect_language_hint


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # Simple languages
        ("Aspose.OCR .NET API", "net"),
        ("RecognizeImage c#", "net"),
        ("dotnet barcode", "net"),
        ("csharp example", "net"),
        ("Java Aspose.PDF", "java"),
        ("python example", "python"),
        ("c++ recognition", "cpp"),
        # Compound languages must NOT match their simple constituents
        ("PythonNet recognition", "python-net"),
        ("python-net API", "python-net"),
        ("python.net module", "python-net"),
        ("PythonJava bridge", "python-java"),
        ("python-java API", "python-java"),
        ("NodejsCpp module", "nodejs-cpp"),
        ("nodejs-cpp binding", "nodejs-cpp"),
        ("JavascriptCpp API", "javascript-cpp"),
        ("javascript-cpp binding", "javascript-cpp"),
        ("GoCpp wrapper", "go-cpp"),
        ("go-cpp binding", "go-cpp"),
        ("AndroidJava SDK", "androidjava"),
        ("android-java setup", "androidjava"),
        # No language detected
        ("Aspose.OCR overview", None),
        ("how to recognize text", None),
    ],
)
def test_detect_language_hint(query: str, expected: str | None) -> None:
    assert _detect_language_hint(query) == expected
