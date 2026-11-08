"""Shared evidence checks for task-oriented API ranking and context promotion."""
import re

from adcs.retrieval.models import QueryPlan
from adcs.retrieval.profiles import profile_for, words
from adcs.retrieval.retrieval_models import HybridCandidate

_NOISE = frozenset('how do i to a an the in for with using use can of as and or net'.split())


def preferred_api(plan: QueryPlan, candidate: HybridCandidate) -> bool:
    meta = candidate.metadata
    if meta.source_kind != 'apiref' or plan.intent != 'how_to':
        return False
    profile = profile_for(meta.product_id, meta.programming_language)
    return bool(profile and (meta.symbol_fqn or '').casefold() in {
        target.casefold() for target in profile.targets(plan.normalized_query)
    })


def api_task_relevant(plan: QueryPlan, candidate: HybridCandidate) -> bool:
    """Reserve API context only with task evidence, not a rank prior alone.

    Profile preferences are explicit evidence. Otherwise require at least half
    of meaningful query terms in the signature/name/summary AND a name/signature
    match. This guards against example-only matches in unrelated API summaries.
    Non-how-to intents retain their existing selection behavior.
    """
    meta = candidate.metadata
    if meta.source_kind != 'apiref' or plan.intent != 'how_to':
        return True
    if preferred_api(plan, candidate):
        return True
    query = re.sub(r'\bAspose\.\w+\b', '', plan.normalized_query, flags=re.I)
    terms = words(query) - _NOISE
    if not terms:
        return False
    signature = meta.text.split('\n', 1)[0]
    identity = words((meta.symbol_fqn or meta.title) + ' ' + signature)
    content = identity | words(meta.text)
    return bool(terms & identity) and len(terms & content) / len(terms) >= 0.5
