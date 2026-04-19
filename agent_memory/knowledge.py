"""
Deterministic knowledge layer — no Claude calls.
All reads/writes to /memory/knowledge and /memory/sources go through here.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from config import (
    CONFLICT_CONFIDENCE_CAP,
    KNOWLEDGE_DIR,
    QUALITY_TIERS,
    SOURCES_DIR,
    WORKING_DIR,
)

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

def init_memory_dirs() -> None:
    """Create the memory directory tree if it doesn't exist."""
    for d in (KNOWLEDGE_DIR, WORKING_DIR, SOURCES_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Domain file I/O
# ---------------------------------------------------------------------------

def init_domain(domain: str) -> None:
    """Create an empty domain file if one doesn't already exist."""
    path = KNOWLEDGE_DIR / f"{domain}.json"
    if not path.exists():
        _write_json(path, {
            "domain": domain,
            "updated_at": _now(),
            "open_questions": [],
            "facts": [],
        })


def load_domain(domain: str) -> dict:
    """Read and return the full domain dict, initializing the file if needed."""
    init_domain(domain)
    return _read_json(KNOWLEDGE_DIR / f"{domain}.json")


def save_domain(domain: str, data: dict) -> None:
    """Write the domain dict back to disk, stamping updated_at."""
    data["updated_at"] = _now()
    _write_json(KNOWLEDGE_DIR / f"{domain}.json", data)


def add_open_question(domain: str, question: str) -> None:
    """Append to open_questions if the question isn't already recorded."""
    data = load_domain(domain)
    if question not in data["open_questions"]:
        data["open_questions"].append(question)
        save_domain(domain, data)


# ---------------------------------------------------------------------------
# Fact merging (core logic)
# ---------------------------------------------------------------------------

def merge_fact(
    domain: str,
    claim: str,
    confidence: float,
    confidence_reason: str,
    source_id: str,
    quality_tier: str,
    contradiction_checker: Optional[Callable[[str, str], dict]] = None,
) -> dict:
    """
    Merge a new fact into the specified domain file.

    If contradiction_checker is provided (claude.detect_contradiction), it is
    called on existing facts that share keywords with the new claim. Resolution
    is then fully deterministic: higher quality_tier wins; same tier → newer wins.
    Both sides have confidence capped at CONFLICT_CONFIDENCE_CAP.

    Returns {"fact": <merged fact dict>, "conflicts_resolved": [...]}.
    """
    data = load_domain(domain)

    new_fact: dict = {
        "claim": claim,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "source_id": source_id,
        "quality_tier": quality_tier,
        "updated_at": _now(),
        "superseded": False,
    }

    conflicts_resolved: list[dict] = []

    if contradiction_checker:
        for existing in data["facts"]:
            if existing["superseded"]:
                continue
            if not _keyword_overlap(claim, existing["claim"]):
                continue

            result = contradiction_checker(claim, existing["claim"])
            if not result.get("contradicts"):
                continue

            winner_claim, loser_claim, rule = _resolve(new_fact, existing, quality_tier)

            conflicts_resolved.append({
                "domain": domain,
                "winning_claim": winner_claim,
                "losing_claim": loser_claim,
                "rule_applied": rule,
                "confidence_after": CONFLICT_CONFIDENCE_CAP,
            })

    data["facts"].append(new_fact)
    save_domain(domain, data)

    return {"fact": new_fact, "conflicts_resolved": conflicts_resolved}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def load_facts_for_retrieval(domains: list[str]) -> list[dict]:
    """
    Return all non-superseded facts from the given domains, sorted by
    confidence descending. Each fact gains a 'domain' key for citation.
    """
    facts: list[dict] = []
    for domain in domains:
        data = load_domain(domain)
        for fact in data["facts"]:
            if not fact.get("superseded"):
                facts.append({**fact, "domain": domain})
    facts.sort(key=lambda f: f["confidence"], reverse=True)
    return facts


# ---------------------------------------------------------------------------
# Source provenance
# ---------------------------------------------------------------------------

def write_source(source_data: dict) -> None:
    """Write a source provenance record to /sources/."""
    source_id = source_data["source_id"]
    _write_json(SOURCES_DIR / f"{source_id}.json", source_data)


def load_source(source_id: str) -> Optional[dict]:
    path = SOURCES_DIR / f"{source_id}.json"
    return _read_json(path) if path.exists() else None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "of", "in", "on", "at", "to", "for", "with",
    "by", "from", "it", "its", "this", "that", "and", "or", "but", "not", "no",
}


def _keyword_overlap(a: str, b: str) -> bool:
    """Return True if the two claims share at least one non-stopword token.

    This is a cheap pre-filter so we only call claude.detect_contradiction on
    pairs that plausibly discuss the same subject.
    """
    def tokens(text: str) -> set[str]:
        return {
            w.lower().strip(".,;:!?\"'")
            for w in text.split()
            if w.lower().strip(".,;:!?\"'") not in _STOPWORDS
        }
    return bool(tokens(a) & tokens(b))


def _resolve(new_fact: dict, existing: dict, new_tier_name: str) -> tuple[str, str, str]:
    """
    Deterministically pick winner/loser and mutate both facts in place.
    Returns (winner_claim, loser_claim, rule_description).
    """
    new_rank = QUALITY_TIERS.get(new_tier_name, 0)
    existing_rank = QUALITY_TIERS.get(existing.get("quality_tier", "conversation"), 0)

    if new_rank > existing_rank:
        _mark_loser(existing, f"Conflict: overridden by higher-tier source ({new_tier_name})")
        _cap_winner(new_fact)
        rule = f"{new_tier_name} (rank {new_rank}) beats {existing.get('quality_tier')} (rank {existing_rank})"
        return new_fact["claim"], existing["claim"], rule

    if existing_rank > new_rank:
        _mark_loser(new_fact, f"Conflict: overridden by higher-tier source ({existing.get('quality_tier')})")
        _cap_winner(existing)
        rule = f"{existing.get('quality_tier')} (rank {existing_rank}) beats {new_tier_name} (rank {new_rank})"
        return existing["claim"], new_fact["claim"], rule

    # Same tier — newer timestamp wins
    if new_fact["updated_at"] >= existing.get("updated_at", ""):
        _mark_loser(existing, f"Conflict: same tier ({new_tier_name}), newer source wins")
        _cap_winner(new_fact)
        rule = f"same tier ({new_tier_name}), recency tiebreak: new wins"
        return new_fact["claim"], existing["claim"], rule

    _mark_loser(new_fact, f"Conflict: same tier ({new_tier_name}), existing source is newer")
    _cap_winner(existing)
    rule = f"same tier ({new_tier_name}), recency tiebreak: existing wins"
    return existing["claim"], new_fact["claim"], rule


def _mark_loser(fact: dict, reason: str) -> None:
    fact["superseded"] = True
    fact["confidence"] = min(fact["confidence"], CONFLICT_CONFIDENCE_CAP)
    fact["confidence_reason"] = reason


def _cap_winner(fact: dict) -> None:
    # Winner is still capped — a resolved conflict introduces uncertainty
    fact["confidence"] = min(fact["confidence"], CONFLICT_CONFIDENCE_CAP)
    fact["confidence_reason"] += " [confidence capped: conflict detected with another source]"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _write_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
