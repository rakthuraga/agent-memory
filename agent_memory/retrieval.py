"""
Retrieval layer — deterministic except for the claude.classify_domain fallback.
Decides whether to retrieve, selects domains, budgets facts, writes active_context.json.
"""

import json
from datetime import datetime, timezone

import claude
import knowledge
from config import (
    CHARS_PER_TOKEN,
    KEYWORD_MAP,
    TOKEN_BUDGET,
    WORKING_DIR,
)

_ACTIVE_CONTEXT_PATH = WORKING_DIR / "active_context.json"

# Query phrases that indicate the user is referencing prior conversation
_CONVERSATIONAL_REFS = (
    "you said", "you told", "earlier you", "just told me",
    "we discussed", "you mentioned", "as you said", "what did you say",
)

# If primary domains return fewer than this many facts, also search misc
_MIN_PRIMARY_FACTS = 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_context(query: str) -> dict:
    """
    Full retrieval pipeline for a single query.
    Returns the active_context dict and writes it to working/active_context.json.
    """
    skip, reason = _should_skip(query)

    if skip:
        ctx = _build_context(
            query=query, domains=[], facts=[],
            token_estimate=0, truncated=False,
            skip_retrieval=True, skip_reason=reason,
        )
        _write_context(ctx)
        return ctx

    domains = _select_domains(query)
    facts = knowledge.load_facts_for_retrieval(domains)

    # Supplement with misc when primary domains are sparse
    if len(facts) < _MIN_PRIMARY_FACTS and "misc" not in domains:
        domains = domains + ["misc"]
        facts = knowledge.load_facts_for_retrieval(domains)

    budgeted_facts, token_estimate, truncated = _apply_budget(facts)

    ctx = _build_context(
        query=query, domains=domains, facts=budgeted_facts,
        token_estimate=token_estimate, truncated=truncated,
        skip_retrieval=False, skip_reason=None,
    )
    _write_context(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _should_skip(query: str) -> tuple[bool, str | None]:
    """Return (True, reason) if this query doesn't need a knowledge lookup."""
    q = query.strip().lower()

    for phrase in _CONVERSATIONAL_REFS:
        if phrase in q:
            return True, f"conversational reference: '{phrase}'"

    # Short query with no domain signal → likely greeting or acknowledgment
    words = [w.strip(".,;:?!") for w in q.split()]
    if len(words) <= 4 and not any(w in KEYWORD_MAP for w in words):
        return True, "short query with no domain keywords"

    return False, None


def _select_domains(query: str) -> list[str]:
    """
    Keyword-first domain routing; falls back to claude.classify_domain if
    no keyword match is found. Always returns at least one domain.
    """
    words = [w.strip(".,;:?!") for w in query.lower().split()]
    matched: set[str] = set()

    # Single-word matches
    for word in words:
        if word in KEYWORD_MAP:
            matched.add(KEYWORD_MAP[word])

    # Bigram matches for two-word phrases ("use case", "open source", etc.)
    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i + 1]}"
        if bigram in KEYWORD_MAP:
            matched.add(KEYWORD_MAP[bigram])

    if matched:
        return sorted(matched)

    # No keyword hit — ask Claude (rare; ~one cheap call)
    return [claude.classify_domain(query)]


def _apply_budget(facts: list[dict]) -> tuple[list[dict], int, bool]:
    """
    Greedily include facts (confidence-desc order) until TOKEN_BUDGET is reached.
    Returns (included_facts, token_estimate, truncated).
    """
    included: list[dict] = []
    total_chars = 0
    budget_chars = TOKEN_BUDGET * CHARS_PER_TOKEN

    for fact in facts:
        fact_chars = len(json.dumps(fact))
        if total_chars + fact_chars > budget_chars:
            return included, total_chars // CHARS_PER_TOKEN, True
        included.append(fact)
        total_chars += fact_chars

    return included, total_chars // CHARS_PER_TOKEN, False


def _build_context(
    query: str,
    domains: list[str],
    facts: list[dict],
    token_estimate: int,
    truncated: bool,
    skip_retrieval: bool,
    skip_reason: str | None,
) -> dict:
    return {
        "assembled_at": _now(),
        "query": query,
        "retrieved_domains": domains,
        "skip_retrieval": skip_retrieval,
        "skip_reason": skip_reason,
        "facts_included": facts,
        "token_estimate": token_estimate,
        "truncated": truncated,
    }


def _write_context(ctx: dict) -> None:
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    with open(_ACTIVE_CONTEXT_PATH, "w") as f:
        json.dump(ctx, f, indent=2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
