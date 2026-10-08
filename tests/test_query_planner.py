from __future__ import annotations

import hashlib
import os

from adcs.retrieval import QueryPlanner, QueryPlannerInput


def test_query_planner_normalizes_query_and_emits_debug_metadata() -> None:
    planner = QueryPlanner()
    request = QueryPlannerInput(
        query="  How do I   use Aspose.OCR.Engine.Recognize   in C#?  ",
        product_id="Aspose.OCR",
        programming_language="c#",
        version="v25.1",
        doc_locale="fr-FR",
        strict_version=True,
    )

    plan = planner.plan(request=request)

    assert plan.normalized_query == "use Aspose.OCR.Engine.Recognize in C#?"
    assert plan.symbol_candidates == ("Aspose.OCR.Engine.Recognize",)
    assert plan.intent == "symbol_lookup"
    assert plan.intent_subtype == "symbol_reference"
    assert plan.filters.product_id == "aspose.ocr"
    assert plan.filters.programming_language == "net"
    assert plan.filters.strict_version_value == "25.1"
    assert plan.filters.locale_routing_order == ("fr", "en")
    assert plan.debug.removed_noise_prefixes == ("how do i",)
    assert plan.debug.intent == "symbol_lookup"
    assert plan.debug.intent_subtype == "symbol_reference"
    assert plan.debug.intent_reason_codes == ("symbol_candidate",)
    assert plan.debug.detected_version_tokens == ()
    assert plan.debug.prefers_latest_stable is False
    assert plan.debug.filter_debug.locale_routing_order == ("fr", "en")
    # Assert the properties, not the digest. Pinning the exact bare SHA-256 of
    # the query would fix the hashing scheme in place: the fingerprint is an
    # HMAC keyed from ADCS_HASH_SECRET so it is a pseudonym rather than a
    # reversible encoding, and a test that asserts the plaintext digest would
    # forbid exactly that design.
    assert len(plan.query_fingerprint) == 64
    assert all(char in "0123456789abcdef" for char in plan.query_fingerprint)
    assert (
        plan.query_fingerprint
        != hashlib.sha256(plan.normalized_query.lower().encode("utf-8")).hexdigest()
        or not os.environ.get("ADCS_HASH_SECRET")
    ), "with a key configured the fingerprint must not equal the plaintext digest"


def test_query_planner_is_deterministic_for_same_input() -> None:
    planner = QueryPlanner()
    request = QueryPlannerInput(
        query="Please explain Aspose.OCR.Engine.Recognize options",
        product_id="aspose.ocr",
        programming_language="dotnet",
        version="25.x",
        doc_locale="en-US",
        strict_version=False,
    )

    first_plan = planner.plan(request=request)
    second_plan = planner.plan(request=request)

    assert first_plan == second_plan


def test_query_planner_classifies_release_and_troubleshooting_intents() -> None:
    planner = QueryPlanner()

    release_plan = planner.plan(
        request=QueryPlannerInput(
            query="What changed in Aspose OCR 25.1 release notes?",
            product_id="aspose.ocr",
            programming_language="net",
        )
    )
    troubleshooting_plan = planner.plan(
        request=QueryPlannerInput(
            query="Aspose OCR throws an error when recognizing skewed images",
            product_id="aspose.ocr",
            programming_language="net",
        )
    )

    assert release_plan.intent == "release_notes"
    assert release_plan.intent_subtype == "latest_release"
    assert "version_token" in release_plan.intent_reason_codes
    assert troubleshooting_plan.intent == "troubleshooting"
    assert troubleshooting_plan.intent_subtype == "runtime_failure"


def test_query_planner_marks_latest_stable_release_queries() -> None:
    planner = QueryPlanner()

    plan = planner.plan(
        request=QueryPlannerInput(
            query="Show me the latest stable Aspose OCR migration notes for 25.1",
            product_id="aspose.ocr",
            programming_language="net",
        )
    )

    assert plan.intent == "release_notes"
    assert plan.intent_subtype == "migration"
    assert "migration_keyword" in plan.intent_reason_codes
    assert "latest_stable_hint" in plan.intent_reason_codes
    assert plan.detected_version_tokens == ("25.1",)
    assert plan.prefers_latest_stable is True


def test_query_planner_truncates_excessively_long_queries() -> None:
    planner = QueryPlanner()
    long_query = "Aspose OCR recognize " * 200  # ~4200 chars

    plan = planner.plan(
        request=QueryPlannerInput(
            query=long_query,
            product_id="aspose.ocr",
            programming_language="net",
        )
    )

    assert len(plan.normalized_query) <= 2000


def test_mail_merge_product_mention_is_how_to_not_symbol():
    plan = QueryPlanner().plan(request=QueryPlannerInput(
        query="How do I perform mail merge in Aspose.Words for .NET?",
        product_id="aspose.words", programming_language="net",
    ))
    assert plan.intent == "how_to"
    assert plan.symbol_candidates == ()


def test_bare_product_namespace_and_document_member_remain_symbol_lookups():
    for query in (
        "Aspose.Words", "Aspose.Words.Document", "How do I use Aspose.Words.Document.Save?"
    ):
        plan = QueryPlanner().plan(request=QueryPlannerInput(
            query=query, product_id="aspose.words", programming_language="net",
        ))
        assert plan.intent == "symbol_lookup"
        assert plan.symbol_candidates
