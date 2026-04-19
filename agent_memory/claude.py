"""
All Claude API calls live here — the only file that imports anthropic.
Each function handles one semantic task and returns a typed result.
Malformed model output is caught and replaced with a safe fallback.
"""

import json
from typing import Any

import anthropic

from config import DOMAINS

MODEL = "claude-sonnet-4-6"

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

# Injected into every domain-aware prompt so Claude uses only valid names
_DOMAIN_LIST = ", ".join(DOMAINS)
_DOMAIN_GUIDE = "\n".join(
    f"  {d}: {desc}"
    for d, desc in {
        "company_overview": "mission, founding, location, size, industry",
        "products": "features, use cases, integrations, APIs, workflows",
        "pricing": "plans, tiers, cost, billing, subscriptions",
        "team": "founders, leadership, employees, culture",
        "technology": "tech stack, architecture, infrastructure, frameworks",
        "misc": "anything that doesn't fit the above categories",
    }.items()
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_facts(text: str, source_type: str) -> list[dict]:
    """
    Extract structured company facts from raw text.
    Returns a list of fact dicts; [] if nothing can be extracted or on parse failure.
    """
    prompt = f"""Extract structured facts about a company from the text below.
Source type: {source_type}

Return a JSON array. Each element must have exactly these keys:
- "domain": one of [{_DOMAIN_LIST}]
- "claim": one specific factual statement, one sentence only
- "confidence": 0.0–1.0 (lower if inferred or behind a gate; higher if explicit)
- "confidence_reason": brief phrase explaining the score
- "open_questions": list of strings for things that were unclear or missing

Domain guide:
{_DOMAIN_GUIDE}

Rules:
- One claim per object. Do not bundle multiple facts.
- If pricing is gated or absent, add an open_question instead of guessing.
- Return [] if no facts can be extracted.
- Return JSON only — no explanation, no markdown fences.

Text:
{text[:6000]}"""

    raw = _call(prompt, max_tokens=2000)
    result = _parse_json(raw, fallback=[])
    return result if isinstance(result, list) else []


def detect_contradiction(claim_a: str, claim_b: str) -> dict:
    """
    Determine whether two claims genuinely contradict each other.
    Returns {"contradicts": bool, "reason": str}.
    Falls back to non-contradicting on parse failure (conservative default).
    """
    prompt = f"""Do these two claims contradict each other?

Claim A: {claim_a}
Claim B: {claim_b}

A contradiction means both cannot be true simultaneously.
Different plans or different products are NOT contradictions.

Return JSON only — no markdown, no explanation:
{{"contradicts": true or false, "reason": "one-sentence explanation"}}"""

    raw = _call(prompt, max_tokens=120)
    result = _parse_json(raw, fallback={"contradicts": False, "reason": "parse error"})
    if not isinstance(result, dict) or "contradicts" not in result:
        return {"contradicts": False, "reason": "malformed response"}
    return result


def classify_domain(text: str) -> str:
    """
    Classify a claim or query into one of the fixed domains.
    Returns a valid domain name string; falls back to 'misc'.
    """
    prompt = f"""Which domain best describes this text?

Text: {text}

Domains:
{_DOMAIN_GUIDE}

Return JSON only: {{"domain": "<domain name>"}}
The domain must be one of: {_DOMAIN_LIST}"""

    raw = _call(prompt, max_tokens=60)
    result = _parse_json(raw, fallback={"domain": "misc"})
    domain = result.get("domain", "misc") if isinstance(result, dict) else "misc"
    return domain if domain in DOMAINS else "misc"


def answer_question(context: list[dict], history: list[dict], query: str) -> str:
    """
    Answer a user question from assembled knowledge context and session history.

    context: fact dicts from load_facts_for_retrieval (may be empty)
    history: turn dicts [{user, assistant}] from session_history
    query:   the current user question

    Returns a plain text answer. No JSON parsing — raw response is the answer.
    """
    # Format knowledge context, tagging conversation-sourced facts explicitly
    if context:
        lines = []
        for f in context:
            is_conversation = f.get("quality_tier") == "conversation"
            tag = " [user-provided]" if is_conversation else ""
            lines.append(
                f"[{f['domain']}] ({f['confidence']:.0%} confidence){tag} {f['claim']}"
            )
        knowledge_block = "Relevant company knowledge:\n" + "\n".join(lines)
    else:
        knowledge_block = "No relevant knowledge found in memory for this question."

    # Format conversation history
    history_block = ""
    if history:
        turns = []
        for t in history:
            turns.append(f"User: {t['user']}")
            turns.append(f"Assistant: {t['assistant']}")
        history_block = "\n\nConversation so far:\n" + "\n".join(turns)

    system = (
        "You are a company knowledge assistant answering questions strictly from the "
        "provided knowledge. Cite the source domain in brackets (e.g. [pricing]) when "
        "using a fact. If a fact's confidence is below 70%, flag it as uncertain. "
        "Facts marked [user-provided] came from user assertions during conversation, "
        "not from verified sources — surface them but label them as unverified. "
        "If a [user-provided] fact conflicts with a verified fact, note both and "
        "state clearly which source each came from. "
        "Say \"I don't know\" if the knowledge base has no relevant information — "
        "do not speculate beyond what is provided."
    )

    user_msg = f"{knowledge_block}{history_block}\n\nQuestion: {query}"
    return _call(user_msg, system=system, max_tokens=600)


def detect_new_facts(user_turn: str) -> list[dict]:
    """
    Detect whether the user is asserting new facts about the company.
    Returns a list of {claim, domain, confidence} dicts, or [] if none found.
    """
    prompt = f"""A user said the following during a conversation about a company:
"{user_turn}"

Is the user asserting new factual information about the company (not asking a question)?
If yes, extract those facts. If no, return [].

Return a JSON array. Each element must have:
- "claim": the specific factual statement
- "domain": one of [{_DOMAIN_LIST}]
- "confidence": 0.75 (standard for user-asserted facts)

Domain guide:
{_DOMAIN_GUIDE}

Return JSON only — no markdown, no explanation. Return [] if no new facts are stated."""

    raw = _call(prompt, max_tokens=400)
    result = _parse_json(raw, fallback=[])
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call(user_message: str, system: str = "Return JSON only.", max_tokens: int = 1000) -> str:
    """Make a single Claude API call and return the text content."""
    message = _client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text.strip()


def _parse_json(text: str, fallback: Any) -> Any:
    """Parse JSON from model output, stripping markdown fences if present."""
    cleaned = text
    if cleaned.startswith("```"):
        # Remove opening fence line and closing fence
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:])
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        return json.loads(cleaned.strip())
    except (json.JSONDecodeError, ValueError):
        return fallback
