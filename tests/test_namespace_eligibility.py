from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from adcs.api.apiref_symbol_query import (
    ApiRefSymbolService,
    GetSymbolRequest,
    ListMembersRequest,
    LookupRequest,
    SearchSymbolsRequest,
)
from adcs.api.public_docs_query import GetSymbolDocRequest, PublicQueryService
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
    PostgresApiRefSymbolStore,
)
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.retrieval.context_packer import ContextPacker
from adcs.retrieval.models import QueryPlannerInput
from adcs.retrieval.profiles import EligibleSymbolStore, profile_for, symbol_allowed
from adcs.retrieval.query_planner import QueryPlanner
from adcs.retrieval.retrieval_models import HybridRetrievalResult
from adcs.retrieval.translation_fallback import TranslationFallbackService
from adcs.retrieval.two_source_retriever import ApiRefRetriever, TwoSourceRetriever

pytestmark = pytest.mark.usefixtures("sample_retrieval_catalog")

SCOPE = ApiRefScope(product='aspose.words', language='net', version='25.4', locale='en')
BLOCKED = 'Aspose.Words.LowCode.MailMerger.Execute'
ALLOWED = 'Aspose.Words.MailMerging.MailMerge.Execute'


def symbol(fqn):
    return ApiRefSymbol(
        snapshot_id='s', product=SCOPE.product, language=SCOPE.language, version=SCOPE.version,
        locale=SCOPE.locale, kind='method', member_fqn=fqn, name='Execute',
        parent_fqn=fqn.rsplit('.', 1)[0], signature='public void Execute(DataTable table)',
        canonical_url='https://reference.aspose.com/words/net/' + fqn.lower() + '/',
        is_deprecated=False, summary='Execute mail merge', payload={},
    )


def store():
    result = InMemoryApiRefSymbolStore()
    result.upsert_symbols([symbol(BLOCKED), symbol(ALLOWED)])
    result.flip_active_snapshot(scope=SCOPE, snapshot_id='s')
    return result


@pytest.mark.parametrize('fqn,allowed', [
    ('Aspose.Words.Lowcode', False), (BLOCKED, False), (BLOCKED.upper(), False),
    ('Aspose.Words.LowcodeExtra.Execute', True), ('Aspose.Words.Other.Lowcode.Execute', True),
    (ALLOWED, True),
])
def test_namespace_boundary(fqn, allowed):
    assert symbol_allowed('aspose.words', 'net', fqn) is allowed
    assert symbol_allowed('aspose.words', 'java', fqn)
    assert symbol_allowed('aspose.cells', 'net', fqn)


def test_conflict_validation_and_unmodified_profile_default():
    profile = profile_for('aspose.words', 'net')
    data = profile.model_dump()
    data['rules'][0]['preferred_symbols'] = [BLOCKED]
    with pytest.raises(ValidationError, match='conflicts'):
        type(profile).model_validate(data)
    data['rules'] = []
    del data['excluded_namespaces']
    assert type(profile).model_validate(data).allows(BLOCKED)


def test_memory_filters_before_limits_and_direct_access():
    source = store()
    assert source.search_symbols(pattern='Execute', scope=SCOPE, limit=1) == (symbol(ALLOWED),)
    assert source.fts_search(query='mail merge', scope=SCOPE, limit=1) == (symbol(ALLOWED),)
    assert source.get_symbol(member_fqn=BLOCKED, scope=SCOPE) == ()
    assert source.list_overloads(member_fqn=BLOCKED, scope=SCOPE) == ()
    assert source.list_members(parent_fqn=BLOCKED.rsplit('.', 1)[0], scope=SCOPE) == ()


def test_postgres_predicate_is_bound_and_precedes_limits_for_all_read_paths():
    source = object.__new__(PostgresApiRefSymbolStore)
    statements = []
    source._query = lambda sql, params: statements.append((sql, params)) or ()
    source.search_symbols(pattern='Execute', scope=SCOPE, limit=1)
    source.fts_search(query='mail merge', scope=SCOPE, limit=1)
    source.get_symbol(member_fqn=BLOCKED, scope=SCOPE)
    source.list_overloads(member_fqn=BLOCKED, scope=SCOPE)
    source.list_members(parent_fqn='Aspose.Words', scope=SCOPE)
    for sql, params in statements:
        assert 'lower(member_fqn)=:excluded_ns_0' in sql
        assert "(:excluded_ns_0 || '.')" in sql
        assert params['excluded_ns_0'] == 'aspose.words.lowcode'
        assert 'aspose.words.lowcode' not in sql
        if 'LIMIT' in sql:
            assert sql.index('excluded_ns_0') < sql.index('LIMIT')


def test_custom_store_wrapper_and_profile_lookup_cannot_leak_excluded_results():
    class LeakyStore:
        def get_symbol(self, **kwargs):
            return (symbol(BLOCKED), symbol(ALLOWED))
        search_symbols = get_symbol
        fts_search = get_symbol
        list_members = get_symbol
        list_overloads = get_symbol

    wrapped = EligibleSymbolStore(LeakyStore())
    assert wrapped.get_symbol(member_fqn=BLOCKED, scope=SCOPE) == ()
    assert wrapped.list_members(parent_fqn='Aspose.Words', scope=SCOPE) == (symbol(ALLOWED),)
    lane = ApiRefRetriever(store=LeakyStore())
    assert lane.lookup_exact(member_fqn=BLOCKED, scope=SCOPE) == ()
    assert lane.search(query='mail merge', scope=SCOPE, limit=20) == (symbol(ALLOWED),)


def test_structured_services_cannot_bypass_policy():
    service = ApiRefSymbolService(store=store())
    kwargs = dict(product_id=SCOPE.product, language=SCOPE.language, version=SCOPE.version)
    assert not service.get_symbol(request=GetSymbolRequest(**kwargs, symbol_fqn=BLOCKED)).found
    assert service.list_members(request=ListMembersRequest(
        **kwargs, parent_fqn=BLOCKED.rsplit('.', 1)[0],
    )).members == []
    result = service.search_symbols(request=SearchSymbolsRequest(**kwargs, query='Execute'))
    assert BLOCKED not in str(result.model_dump())
    result = service.lookup(request=LookupRequest(**kwargs, query=BLOCKED))
    assert BLOCKED not in str(result.model_dump().get('symbol'))
    assert all(r.member_fqn != BLOCKED for r in result.results)


def test_public_legacy_lookup_does_not_bypass_exclusion(monkeypatch):
    service = PublicQueryService(
        source_hugo_normalization_orchestrator=SourceHugoNormalizationOrchestrationService(),
        translation_fallback_service=TranslationFallbackService(),
    )
    def unexpected(**kwargs):
        pytest.fail('Excluded exact symbol reached legacy lookup')
    monkeypatch.setattr(service, '_qdrant_symbol_lookup', unexpected)
    with pytest.raises(LookupError, match='outside'):
        service.get_symbol_doc(request=GetSymbolDocRequest(
            product_id=SCOPE.product, language=SCOPE.language, symbol_fqn=BLOCKED,
        ))


def test_fusion_and_context_filter_api_candidates_but_keep_documentation():
    blocked = PublicQueryService._apiref_symbol_to_candidate(symbol=symbol(BLOCKED), rank=0)
    allowed = PublicQueryService._apiref_symbol_to_candidate(symbol=symbol(ALLOWED), rank=1)
    docs = replace(blocked, metadata=replace(blocked.metadata, source_kind='docs',
                   candidate_id='documentation', chunk_id='documentation'))
    plan = QueryPlanner().plan(request=QueryPlannerInput(
        query='mail merge', product_id=SCOPE.product, programming_language=SCOPE.language,
    ))
    result = HybridRetrievalResult(
        query_fingerprint=plan.query_fingerprint, normalized_query=plan.normalized_query,
        candidates=(blocked, allowed, docs), dense_candidates_count=3,
        lexical_candidates_count=0, fused_candidates_count=3, dense_weight=1, lexical_weight=0,
    )
    packed = ContextPacker().pack(plan=plan, retrieval_result=result, top_k=2)
    assert {x.candidate_id for x in packed.items} == {
        allowed.metadata.candidate_id, 'documentation',
    }
    service = PublicQueryService(
        source_hugo_normalization_orchestrator=SourceHugoNormalizationOrchestrationService(),
        translation_fallback_service=TranslationFallbackService(),
    )
    fused = service._fuse_apiref_symbols(retrieval_result=result, plan=plan, query='mail merge',
        product_id=SCOPE.product, programming_language=SCOPE.language, version=SCOPE.version)
    assert fused.candidates == (allowed, docs)
    retriever = TwoSourceRetriever(
        docs_lane=SimpleNamespace(search=lambda **kw: (blocked,)),
        apiref_lane=SimpleNamespace(search=lambda **kw: (symbol(BLOCKED),),
                                   lookup_exact=lambda **kw: (symbol(BLOCKED),)),
    )
    unified = retriever.retrieve(query=BLOCKED, scope=SCOPE)
    assert unified.hits == ()
    assert not unified.exact_symbol_hit


def test_legacy_namespace_page_without_symbol_uses_namespace_url_segment():
    from adcs.retrieval.profiles import candidate_allowed

    candidate = PublicQueryService._apiref_symbol_to_candidate(symbol=symbol(BLOCKED), rank=0)
    metadata = replace(candidate.metadata, symbol_fqn=None,
                       canonical_url='https://reference.aspose.com/words/net/aspose.words.lowcode/')
    assert not candidate_allowed(metadata)
    assert candidate_allowed(replace(metadata, source_kind='docs'))
    assert candidate_allowed(replace(metadata,
        canonical_url='https://reference.aspose.com/words/net/aspose.words.lowcodeextra/'))
