from dataclasses import replace

import pytest

from adcs.api.public_docs_query import PublicQueryService
from adcs.indexing.apiref_symbol_store import ApiRefSymbol
from adcs.retrieval.context_packer import _prioritize_source_coverage
from adcs.retrieval.models import QueryPlannerInput
from adcs.retrieval.profiles import profile_for
from adcs.retrieval.query_planner import QueryPlanner
from adcs.retrieval.reranker import AdvancedHeuristicReranker
from adcs.retrieval.task_relevance import api_task_relevant

pytestmark = pytest.mark.usefixtures("sample_retrieval_catalog")


def plan(query):
    return QueryPlanner().plan(request=QueryPlannerInput(
        query=query, product_id='aspose.words', programming_language='net',
    ))


def candidate(fqn, text, rank=0):
    return PublicQueryService._apiref_symbol_to_candidate(symbol=ApiRefSymbol(
        snapshot_id='s', product='aspose.words', language='net', version='latest-stable',
        locale='en', kind='method', member_fqn=fqn, name=fqn.split('.')[-1], parent_fqn=None,
        signature=text, summary='', canonical_url='https://reference.aspose.com/',
        is_deprecated=False, payload={},
    ), rank=rank)


@pytest.mark.parametrize('query', ['How to convert DOC/DOCX to PDF?',
    'Save a Word document as PDF', 'Convert DOC to PDF', 'Convert DOCX to PDF'])
def test_pdf_profile_matches_direction(query):
    assert 'Aspose.Words.Document.Save' in profile_for('aspose.words', 'net').targets(query)


@pytest.mark.parametrize('query', ['Convert PDF to DOCX', 'Convert DOCX to HTML',
    'How do I use Aspose.Words.Document.Save?', 'Convert PDF to Word'])
def test_pdf_profile_does_not_override_other_formats_or_explicit_symbols(query):
    assert not profile_for('aspose.words', 'net').targets(query)


def test_final_reranker_keeps_preferred_api_above_incidental_example_match():
    p = plan('How to convert DOC/DOCX to PDF?')
    unrelated = candidate('Aspose.Words.Math.MathObjectType',
                          'public enum MathObjectType\nDocument doc = new Document("file.docx");')
    save = candidate('Aspose.Words.Document.Save', 'public void Save(string fileName)', rank=1)
    assert not api_task_relevant(p, unrelated)
    assert api_task_relevant(p, save)
    ranked = AdvancedHeuristicReranker().rerank(plan=p, candidates=(unrelated, save), limit=2)
    assert ranked[0].metadata.symbol_fqn == 'Aspose.Words.Document.Save'
    # Cells gets no Words profile boost.
    cells = replace(save, metadata=replace(save.metadata, product_id='aspose.cells'))
    assert not api_task_relevant(p, cells)


def test_context_reservation_skips_unrelated_api():
    p = plan('How to convert DOC/DOCX to PDF?')
    unrelated = candidate('Aspose.Words.Math.MathObjectType', 'public enum MathObjectType')
    save = candidate('Aspose.Words.Document.Save', 'public void Save(string fileName)')
    doc = replace(save, metadata=replace(save.metadata, source_kind='docs', candidate_id='doc'))
    doc2 = replace(doc, metadata=replace(doc.metadata, candidate_id='doc2'))
    assert _prioritize_source_coverage((doc, doc2, unrelated), plan=p) == (doc, doc2, unrelated)
    assert _prioritize_source_coverage((doc, doc2, unrelated, save), plan=p)[1] == save


def test_release_note_penalty_is_specific_to_unversioned_how_to():
    base = candidate('Aspose.Words.Document', 'Convert DOCX to PDF')
    release = replace(base, metadata=replace(base.metadata, source_kind='docs',
                       doc_type='release_note', title='20.9 Release Notes'))
    guide = replace(release, metadata=replace(release.metadata, doc_type='guide', title='Guide'))
    ranker = AdvancedHeuristicReranker()
    result = ranker.rerank(plan=plan('How to convert DOCX to PDF?'),
                          candidates=(release, guide), limit=2)
    assert result[0].metadata.doc_type == 'guide'
    result = ranker.rerank(plan=plan('What changed in release 20.9?'),
                          candidates=(release, guide), limit=2)
    assert result[0].metadata.doc_type == 'release_note'


def test_versioned_how_to_keeps_release_notes_without_extra_penalty():
    p = plan('How to convert DOCX to PDF?')
    versioned = replace(p, filters=replace(p.filters, preferred_version='20.9'))
    base = candidate('Aspose.Words.Document', 'Convert DOCX to PDF')
    release = replace(base, metadata=replace(base.metadata, source_kind='docs',
                       doc_type='release_note', title='20.9 Release Notes'))
    ranker = AdvancedHeuristicReranker()
    generic_score = ranker.rerank(plan=p, candidates=(release,), limit=1)[0].rerank_score
    version_score = ranker.rerank(plan=versioned, candidates=(release,), limit=1)[0].rerank_score
    assert version_score > generic_score


def test_conversion_profile_does_not_boost_api_for_release_question():
    from adcs.retrieval.task_relevance import preferred_api

    p = plan('What changed in DOCX to PDF conversion in release 20.9?')
    assert p.intent == 'release_notes'
    save = candidate('Aspose.Words.Document.Save', 'public void Save(string fileName)')
    assert not preferred_api(p, save)
