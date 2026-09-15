"""Tests for _url_match used in golden eval URL comparison."""

from __future__ import annotations

import pytest

from adcs.quality_gates.golden_eval import _url_match


@pytest.mark.parametrize(
    ("expected", "actual", "should_match"),
    [
        # Forward match: expected is substring of actual
        (
            "docs.aspose.com/ocr/net/quickstart/",
            "https://docs.aspose.com/ocr/net/quickstart/getting-started/",
            True,
        ),
        # Exact match
        (
            "https://docs.aspose.com/ocr/net/api/",
            "https://docs.aspose.com/ocr/net/api/",
            True,
        ),
        # Reverse match with sufficient depth
        (
            "https://docs.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/24-12/",
            "https://docs.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/",
            True,
        ),
        # Reverse match rejected: bare root URL too shallow
        (
            "https://docs.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/",
            "https://docs.aspose.com/net/",
            False,
        ),
        # No match at all
        (
            "https://docs.aspose.com/ocr/net/api/",
            "https://docs.aspose.com/pdf/java/overview/",
            False,
        ),
    ],
)
def test_url_match(expected: str, actual: str, *, should_match: bool) -> None:
    assert _url_match(expected, actual) is should_match
