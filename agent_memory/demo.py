"""
End-to-end demo script.
Edit the CONFIGURATION block below, then run: python demo.py
"""

import json
import sys
from pathlib import Path

import agent
import ingest
import knowledge
from config import DOMAINS, KNOWLEDGE_DIR, SOURCES_DIR, WORKING_DIR

# ============================================================
# CONFIGURATION — edit these before running
# ============================================================

COMPANY_URL = "https://linear.app"

# A second source that introduces new or contradictory information
SECOND_SOURCE_TEXT = """\
Linear Pricing Update — Internal Sales Reference (April 2026)

Linear has updated its pricing effective Q1 2026:
- Free plan: now supports up to 10 members (previously unlimited but feature-limited)
- Business plan: $15 per user per month (the public website may still show $8/user)
- Enterprise plan: starts at $2,500 per month for unlimited seats and priority support

Additional facts confirmed by the sales team:
- Linear now offers a native Figma integration as of March 2026
- The company headcount has grown to over 120 employees
- Linear is headquartered in San Francisco, CA and was founded in 2019
"""

SECOND_SOURCE_LABEL = "linear_internal_sales_deck_april2026"

# 3 questions that span different knowledge domains
DOMAIN_QUESTIONS = [
    "What does this company do and who is it for?",   # → company_overview
    "What are the pricing plans and how much do they cost?",  # → pricing
    "What tools and integrations does it support?",   # → products / technology
]

CONTRADICTION_QUESTION = (
    "What are the current pricing plans? How confident are you in those numbers?"
)

NEW_FACT_STATEMENT = (
    "I just got off a call with their sales team — "
    "the enterprise plan is actually $3,000 per month now."
)

RECALL_QUESTION = "What do you know about their enterprise pricing?"

# ============================================================
# Demo runner
# ============================================================

def main() -> None:
    knowledge.init_memory_dirs()
    _banner("AGENT MEMORY — END-TO-END DEMO")

    # ------------------------------------------------------------------
    # Step 1: Ingest URL
    # ------------------------------------------------------------------
    _section("STEP 1  Ingest company URL")
    print(f"  URL: {COMPANY_URL}\n")

    try:
        summary = ingest.ingest_url(COMPANY_URL)
        _print_ingestion_summary(summary)
    except Exception as e:
        _error(f"URL ingestion failed: {e}")
        print("  Continuing with empty knowledge base.\n")
        summary = {}

    # ------------------------------------------------------------------
    # Step 2: Knowledge state after first ingestion
    # ------------------------------------------------------------------
    _section("STEP 2  Knowledge state after URL ingestion")
    _print_knowledge_state()
    _print_sources_listing()

    # ------------------------------------------------------------------
    # Step 3: Ask questions across domains
    # ------------------------------------------------------------------
    _section("STEP 3  Asking questions across knowledge domains")
    for question in DOMAIN_QUESTIONS:
        _ask(question, show_context=True)

    # ------------------------------------------------------------------
    # Step 4: Ingest second source (with contradictions)
    # ------------------------------------------------------------------
    _section("STEP 4  Ingest second source (contradictory document)")
    print(f"  Label: {SECOND_SOURCE_LABEL}\n")

    try:
        summary2 = ingest.ingest_text(SECOND_SOURCE_TEXT, label=SECOND_SOURCE_LABEL)
        _print_ingestion_summary(summary2)
        _print_conflicts(summary2.get("conflicts_resolved", []))
    except Exception as e:
        _error(f"Second source ingestion failed: {e}")

    # ------------------------------------------------------------------
    # Step 5: Updated knowledge state
    # ------------------------------------------------------------------
    _section("STEP 5  Updated knowledge state (showing superseded facts)")
    _print_knowledge_state(show_superseded=True)
    _print_sources_listing()

    # ------------------------------------------------------------------
    # Step 6: Ask about the contradicted fact
    # ------------------------------------------------------------------
    _section("STEP 6  Asking about a fact that was contradicted")
    _ask(CONTRADICTION_QUESTION, show_context=True)

    # ------------------------------------------------------------------
    # Step 7: User states a new fact mid-conversation
    # ------------------------------------------------------------------
    _section("STEP 7  Multi-turn: user states a new fact")
    print(f"  User: {NEW_FACT_STATEMENT}\n")
    try:
        answer = agent.process_turn(NEW_FACT_STATEMENT)
        print(f"  Assistant: {answer}\n")
    except Exception as e:
        _error(f"Turn failed: {e}")

    print("  Pricing domain after user-stated fact:")
    _print_domain_detail("pricing")

    # ------------------------------------------------------------------
    # Step 8: Recall the stored fact in a later turn
    # ------------------------------------------------------------------
    _section("STEP 8  Recalling the stored fact")
    _ask(RECALL_QUESTION, show_context=True)

    # ------------------------------------------------------------------
    # Step 9: Working memory inspection
    # ------------------------------------------------------------------
    _section("STEP 9  Working memory state")
    _print_active_context()
    _print_session_summary()

    _banner("DEMO COMPLETE")


# ============================================================
# Display helpers
# ============================================================

def _ask(question: str, show_context: bool = False) -> None:
    print(f"  Q: {question}")
    try:
        answer = agent.process_turn(question)
        # Wrap long answers at 80 chars
        for line in _wrap(answer, 80):
            print(f"     {line}")
    except Exception as e:
        _error(f"  Turn failed: {e}")
    if show_context:
        _print_context_snippet()
    print()


def _print_ingestion_summary(summary: dict) -> None:
    print(f"  source_id      : {summary.get('source_id', 'n/a')}")
    print(f"  pages processed: {summary.get('pages_processed', 0)}")
    print(f"  facts added    : {summary.get('facts_added', 0)}")
    print(f"  domains updated: {', '.join(summary.get('domains_updated', [])) or 'none'}")
    print()


def _print_conflicts(conflicts: list[dict]) -> None:
    if not conflicts:
        print("  No conflicts detected.\n")
        return
    print(f"  {len(conflicts)} conflict(s) resolved:")
    for c in conflicts:
        print(f"    domain  : {c.get('domain')}")
        print(f"    winner  : {_clip(c.get('winning_claim', ''))}")
        print(f"    loser   : {_clip(c.get('losing_claim', ''))}")
        print(f"    rule    : {c.get('rule_applied')}")
        print()


def _print_knowledge_state(show_superseded: bool = False) -> None:
    any_found = False
    for domain in DOMAINS:
        path = KNOWLEDGE_DIR / f"{domain}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        active = [f for f in data["facts"] if not f.get("superseded")]
        superseded = [f for f in data["facts"] if f.get("superseded")]
        oqs = data.get("open_questions", [])
        if not active and not superseded:
            continue
        any_found = True
        sup_note = f", {len(superseded)} superseded" if superseded else ""
        print(f"  [{domain}]  {len(active)} active{sup_note}, {len(oqs)} open question(s)")
        for f in active:
            print(f"    ✓ [{int(f['confidence'] * 100):3d}%] {_clip(f['claim'])}")
        if show_superseded:
            for f in superseded:
                print(f"    ✗ [{int(f['confidence'] * 100):3d}%] {_clip(f['claim'])}  ← superseded")
    if not any_found:
        print("  (no facts in knowledge base yet)")
    print()


def _print_domain_detail(domain: str) -> None:
    path = KNOWLEDGE_DIR / f"{domain}.json"
    if not path.exists():
        print(f"  {domain}.json not found\n")
        return
    data = json.loads(path.read_text())
    for f in data["facts"]:
        status = "superseded" if f.get("superseded") else "active"
        print(f"    [{status}] [{int(f['confidence'] * 100)}%] {_clip(f['claim'])}  (src: {f.get('source_id')})")
    print()


def _print_sources_listing() -> None:
    sources = sorted(SOURCES_DIR.glob("*.json"))
    if not sources:
        print("  /sources  (empty)\n")
        return
    print(f"  /sources  ({len(sources)} record(s))")
    for p in sources:
        try:
            d = json.loads(p.read_text())
            print(f"    {p.name}  type={d.get('type')}  domains={d.get('domains_updated')}")
        except Exception:
            print(f"    {p.name}  (unreadable)")
    print()


def _print_context_snippet() -> None:
    path = WORKING_DIR / "active_context.json"
    if not path.exists():
        return
    try:
        ctx = json.loads(path.read_text())
        skip = ctx.get("skip_retrieval", False)
        if skip:
            print(f"     [context] skip_retrieval=True  reason={ctx.get('skip_reason')}")
        else:
            print(
                f"     [context] domains={ctx.get('retrieved_domains')}  "
                f"facts={len(ctx.get('facts_included', []))}  "
                f"tokens≈{ctx.get('token_estimate')}  "
                f"truncated={ctx.get('truncated')}"
            )
    except Exception:
        pass


def _print_active_context() -> None:
    path = WORKING_DIR / "active_context.json"
    if not path.exists():
        print("  active_context.json not found\n")
        return
    print("  working/active_context.json:")
    try:
        ctx = json.loads(path.read_text())
        # Print a readable subset — not the full facts payload
        slim = {k: ctx[k] for k in ("assembled_at", "query", "retrieved_domains",
                                     "skip_retrieval", "skip_reason",
                                     "token_estimate", "truncated")}
        slim["facts_included_count"] = len(ctx.get("facts_included", []))
        print(json.dumps(slim, indent=4))
    except Exception as e:
        _error(str(e))
    print()


def _print_session_summary() -> None:
    path = WORKING_DIR / "session.json"
    if not path.exists():
        print("  session.json not found\n")
        return
    print("  working/session.json:")
    try:
        sess = json.loads(path.read_text())
        print(f"    session_id : {sess.get('session_id')}")
        print(f"    started_at : {sess.get('started_at')}")
        turns = sess.get("turns", [])
        print(f"    turns      : {len(turns)}")
        for i, t in enumerate(turns):
            stored = t.get("facts_stored", [])
            stored_note = f"  → stored: {stored[0][:50]!r}" if stored else ""
            print(f"      [{i+1}] User: {_clip(t['user'])}{stored_note}")
    except Exception as e:
        _error(str(e))
    print()


# ============================================================
# Formatting utilities
# ============================================================

def _banner(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  {title}")
    print(f"{bar}\n")


def _section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}\n")


def _error(msg: str) -> None:
    print(f"  [error] {msg}", file=sys.stderr)


def _clip(text: str, width: int = 78) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines, current = [], []
    length = 0
    for word in words:
        if length + len(word) + 1 > width and current:
            lines.append(" ".join(current))
            current, length = [word], len(word)
        else:
            current.append(word)
            length += len(word) + 1
    if current:
        lines.append(" ".join(current))
    return lines or [""]


if __name__ == "__main__":
    main()
