"""
Single-turn orchestration: retrieve → answer → store new facts → update history.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import claude
import knowledge
import retrieval
from config import DOMAINS, SESSION_WINDOW, WORKING_DIR

_SESSION_PATH = WORKING_DIR / "session.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_turn(query: str) -> str:
    """
    Handle one user query end-to-end.
    Returns the assistant's answer as a plain string.
    """
    knowledge.init_memory_dirs()
    session = _load_session()

    # Retrieve and assemble context (writes active_context.json as a side effect)
    ctx = retrieval.assemble_context(query)
    facts = ctx.get("facts_included", [])
    retrieved_domains = ctx.get("retrieved_domains", [])

    # Answer from memory
    history_turns = session["turns"][-SESSION_WINDOW:]
    answer = claude.answer_question(facts, history_turns, query)
    if not answer or not answer.strip():
        answer = "I wasn't able to generate a response — please try again."

    # Detect and store any new facts the user asserted
    turn_index = len(session["turns"])
    facts_stored = _store_new_facts(query, session["session_id"], turn_index)

    # Update session history
    session["turns"].append({
        "user": query,
        "assistant": answer,
        "retrieved_domains": retrieved_domains,
        "facts_stored": facts_stored,
    })
    session["turns"] = session["turns"][-SESSION_WINDOW:]
    _save_session(session)

    return answer


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def _load_session() -> dict:
    if _SESSION_PATH.exists():
        try:
            with open(_SESSION_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return _init_session()


def _save_session(session: dict) -> None:
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    with open(_SESSION_PATH, "w") as f:
        json.dump(session, f, indent=2)


def _init_session() -> dict:
    session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return {
        "session_id": session_id,
        "started_at": _now(),
        "turns": [],
    }


# ---------------------------------------------------------------------------
# Store-during-conversation
# ---------------------------------------------------------------------------

def _store_new_facts(user_turn: str, session_id: str, turn_index: int) -> list[str]:
    """
    Detect user-asserted facts, merge them into knowledge, and write provenance.
    Returns a list of stored claim strings for session history logging.
    """
    try:
        detected = claude.detect_new_facts(user_turn)
    except Exception:
        return []

    if not detected:
        return []

    source_id = f"conv_{session_id}_{turn_index:03d}"
    stored_claims: list[str] = []
    domains_updated: set[str] = set()

    for fact in detected:
        claim = fact.get("claim", "").strip()
        if not claim:
            continue

        domain = fact.get("domain", "misc")
        if domain not in DOMAINS:
            domain = claude.classify_domain(claim)

        confidence = float(fact.get("confidence", 0.75))

        try:
            knowledge.merge_fact(
                domain=domain,
                claim=claim,
                confidence=confidence,
                confidence_reason="User-asserted during conversation",
                source_id=source_id,
                quality_tier="conversation",
                contradiction_checker=claude.detect_contradiction,
            )
            stored_claims.append(claim)
            domains_updated.add(domain)
        except Exception as e:
            print(f"[agent] Failed to store fact '{claim[:60]}': {e}")

    if stored_claims:
        knowledge.write_source({
            "source_id": source_id,
            "type": "conversation",
            "content": user_turn,
            "ingested_at": _now(),
            "quality_tier": "conversation",
            "domains_updated": sorted(domains_updated),
        })
        print(f"[agent] Stored {len(stored_claims)} new fact(s) → {sorted(domains_updated)}")

    return stored_claims


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
