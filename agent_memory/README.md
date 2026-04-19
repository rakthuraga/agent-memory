# Agent Memory

This project is a company knowledge agent that ingests websites and documents, extracts structured facts, and answers questions using a persistent memory system.

The goal wasn't just to use an LLM, but to build a system where:

- knowledge is stored explicitly
- conflicts are handled deterministically
- answers are grounded in retrieved data (not hallucinated)

Most of the system (ingestion, merging, retrieval, session state) is written in Python. Claude is only used for extraction, contradiction detection, and answering.
The system is designed so that every answer can be traced back to stored facts, rather than relying on model recall.

---

## How It Works

At a high level, the system follows this flow:

Ingest → Extract facts → Merge into memory → Retrieve → Answer → Learn from user

More concretely:

### Ingestion (`ingest.py`)
- Crawls a URL or reads a document
- Extracts text and chunks it

### Fact Extraction (`claude.extract_facts`)
Converts raw text into structured facts:
```json
{ "domain": "...", "claim": "...", "confidence": 0.0 }
```

### Memory Merge (`knowledge.py`)
Stores facts into domain-based JSON files. Handles:
- duplicate suppression
- contradiction resolution
- confidence updates

### Retrieval (`retrieval.py`)
- Maps query → relevant domains
- Assembles a token-bounded context

### Answering (`claude.answer_question`)
- Generates an answer using only retrieved facts
- Includes confidence + domain citations

### Conversation Learning
- Detects new facts from user input
- Stores them as low-confidence `"conversation"` facts
- Surfaces them later as unverified

---

## Memory Design

### Long-term memory (`/memory/knowledge/`)

Facts are grouped into domains:

- `company_overview`
- `products`
- `pricing`
- `team`
- `technology`
- `misc`

Each domain is a JSON file. Facts look like:

```json
{
  "claim": "Business plan costs $16/month",
  "confidence": 0.6,
  "source_id": "source_001",
  "quality_tier": "primary_url",
  "superseded": false
}
```

Important details:

- Facts are **never deleted**
- Old/conflicting facts are marked `superseded`
- Zero-confidence facts are stored but not used in answers
- Duplicate facts are removed using normalized string matching

## System Guarantees

- Answers are grounded strictly in retrieved facts
- All information is traceable to a source
- Conflicts are preserved and explicitly surfaced
- User-provided data is stored but treated as lowest trust

### Source tracking (`/memory/sources/`)

Every ingestion writes a source record:

- where the data came from
- which domains were updated
- what conflicts were resolved

Conversation facts also get their own source IDs.

### Working memory (`/memory/working/`)

- `active_context.json` — what was retrieved for the current query
- `session.json` — last N turns of conversation

Session history is just a sliding window (no summarization).

---

## Conflict Resolution

Sources are ranked:

```
primary_url > document > secondary_url > conversation
```

When two facts conflict:

1. Check if they're comparable (same type, same entity)
2. Use Claude to detect contradiction
3. Higher-tier source wins
4. Lower-tier fact is marked `superseded`
5. Confidence is capped (conflict introduces uncertainty)

Contradiction detection is scoped to **pricing only**, since:

- that's where conflicts actually matter
- running it everywhere is expensive and noisy

---

## Retrieval + Answering

- Queries are mapped to domains using keyword matching
- If needed, Claude is used as a fallback classifier
- Facts are sorted by confidence and added until a token budget is reached

The model is explicitly instructed to:

- only use provided facts
- cite domains
- flag low-confidence information
- say "I don't know" instead of guessing

---

## Conversation Behavior

After each user message:

1. The system checks if the user stated a new fact
2. If so, it stores it as `quality_tier="conversation"`

These facts:

- are retrievable
- are labeled `[user-provided]`
- are treated as lowest trust

If they conflict with verified data, both are shown.

---

## Design Tradeoffs

| Decision | Reason | Downside |
|---|---|---|
| JSON memory instead of a vector DB | Fully inspectable and debuggable | Weaker semantic retrieval |
| Fixed domains instead of dynamic schema | Simple and predictable retrieval | Edge cases pushed into `misc` |
| Contradiction detection only for pricing | Avoids unnecessary LLM calls and false positives | Other domains don't resolve conflicts as deeply |
| Conversation facts are low-trust | Avoids user input overriding verified sources | Agent feels slightly limited |
| No embeddings / semantic search | Simpler and deterministic | Less robust to unusual phrasing |

---

## Running the Project

Install dependencies:

```bash
pip install anthropic requests beautifulsoup4 pdfplumber
export ANTHROPIC_API_KEY=your_key_here
```

Run the demo:

```bash
rm -rf memory
python demo.py
```

Run the CLI:

```bash
python chat.py
```

---

## Example

```
User: What are the pricing plans?

A:
- Free: $0
- Basic: $10/user/month
- Business: $16/user/month
- Enterprise: custom pricing

User: I heard enterprise is $3000/month

A:
- Stored as [user-provided]
- Conflicts with existing "custom pricing" fact

User: What do you know about enterprise pricing?

A:
- Verified: custom pricing
- User-provided: $3000/month (unverified)
```