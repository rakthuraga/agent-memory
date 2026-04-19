# Claude Code Usage Summary

I used Claude Code as a development assistant while building this system, mainly to help iterate quickly on structure and debug issues as they came up. The overall architecture and design decisions were driven by me, with Claude supporting implementation and refinement.

---

## How I Used Claude

My workflow was generally:

1. Break the system into components (ingestion, knowledge storage, retrieval)
2. Use Claude to scaffold initial implementations
3. Run the system and observe behavior
4. Iterate on specific issues or inefficiencies
5. Refine until the behavior matched the requirements

I treated Claude as a tool for acceleration, not as a source of truth — all outputs were reviewed and adjusted.

---

## Key Iterations

### 1. Initial Ingestion + Fact Extraction

- Built a crawler to ingest company pages
- Extracted structured facts using LLM calls
- Stored results in domain-specific memory

At this stage, the system worked but was inefficient and noisy.

---

### 2. Debugging Long-Running Ingestion

**Issue:**
The demo appeared to run indefinitely and took several minutes to complete.

**Fix:**
- Identified that too many pages were being crawled
- Reduced crawl cap to a smaller number for testing
- Added clearer logging around extraction steps

This significantly reduced runtime and made the system easier to debug.

---

### 3. Reducing Unnecessary LLM Calls

**Issue:**
Extraction was being triggered more often than needed, increasing latency.

**Fix:**
- Ensured extraction only runs once per page
- Added logging before/after extraction to trace behavior

This improved performance and made execution more predictable.

---

### 4. Confidence Filtering

**Issue:**
Low-confidence facts were polluting retrieval results.

**Fix:**
- Introduced confidence thresholds
- Filtered out zero/low-confidence facts from retrieval
- Kept them in storage for transparency

This improved answer quality without losing traceability.

---

### 5. Conflict Resolution / Superseding Facts

- Implemented contradiction detection between facts
- Marked older or conflicting facts as `superseded`
- Verified behavior with direct test cases

This ensures the system can handle evolving or conflicting information cleanly.

---

## Design Philosophy

A key goal was to keep the system **deterministic and inspectable**:

- Retrieval is always grounded in stored facts
- No hallucinated answers
- All outputs are traceable to a source
- Conflicts are explicitly handled, not hidden

Claude was used to speed up iteration, but the system behavior is controlled through explicit logic.

---

## Takeaways

- Claude helped accelerate development, especially for scaffolding and debugging
- Most improvements came from observing system behavior and iterating
- Final system prioritizes reliability, traceability, and clarity over complexity
