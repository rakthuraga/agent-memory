"""
Ingestion orchestration — URL crawl and file/text loading.
No merge logic lives here; this module calls claude.py and knowledge.py.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import claude
import knowledge
from config import DOMAINS, SOURCES_DIR

try:
    import pdfplumber
    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False

# Pages matching these path segments get quality_tier = primary_url
_HIGH_SIGNAL = {
    "pricing", "price", "prices", "plans", "plan",
    "product", "products", "features", "feature",
    "about", "team", "people", "leadership",
    "docs", "documentation", "solutions", "solution",
    "platform", "how-it-works", "why",
}

_MAX_PAGES = 4
_REQUEST_TIMEOUT = 8
_MAX_CHARS_PER_PAGE = 6000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_url(url: str) -> dict:
    """Crawl a URL, extract facts into memory, write provenance. Returns a summary."""
    knowledge.init_memory_dirs()
    source_id = _next_source_id()

    print(f"[ingest] Starting URL crawl: {url}")
    pages = _crawl(url)

    if not pages:
        print("[ingest] No pages fetched — aborting.")
        return _empty_summary(source_id)

    conflicts, domains_updated, facts_added = _process_pages(pages, source_id)

    provenance = {
        "source_id": source_id,
        "type": "url",
        "uri": url,
        "ingested_at": _now(),
        "quality_tier": "primary_url",
        "pages_crawled": [p["url"] for p in pages],
        "domains_updated": sorted(set(domains_updated)),
        "facts_added": facts_added,
        "conflicts_resolved": conflicts,
    }
    knowledge.write_source(provenance)
    print(f"[ingest] Done. {facts_added} facts across {len(pages)} pages → {provenance['domains_updated']}")
    return _summary(provenance)


def ingest_text(text: str, label: str = "pasted_text") -> dict:
    """Ingest raw text (e.g. pasted document), extract facts, write provenance."""
    knowledge.init_memory_dirs()
    source_id = _next_source_id()

    print(f"[ingest] Ingesting text: {label!r} ({len(text)} chars)")
    pages = [{"url": label, "text": text[:_MAX_CHARS_PER_PAGE], "quality_tier": "document"}]
    conflicts, domains_updated, facts_added = _process_pages(pages, source_id)

    provenance = {
        "source_id": source_id,
        "type": "text",
        "uri": label,
        "ingested_at": _now(),
        "quality_tier": "document",
        "pages_crawled": [label],
        "domains_updated": sorted(set(domains_updated)),
        "facts_added": facts_added,
        "conflicts_resolved": conflicts,
    }
    knowledge.write_source(provenance)
    print(f"[ingest] Done. {facts_added} facts → {provenance['domains_updated']}")
    return _summary(provenance)


def ingest_file(filepath: str) -> dict:
    """Load a .txt, .md, or .pdf file and ingest its contents."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _read_pdf(path)
    elif suffix in (".txt", ".md", ""):
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Use .txt, .md, or .pdf.")

    if not text.strip():
        raise ValueError(f"File produced no readable text: {filepath}")

    return ingest_text(text, label=path.name)


# ---------------------------------------------------------------------------
# Crawling
# ---------------------------------------------------------------------------

def _crawl(start_url: str) -> list[dict]:
    """
    Fetch the homepage and a prioritized subset of same-domain links.
    Returns a list of {url, text, quality_tier} dicts.
    """
    homepage_html = _fetch_html(start_url)
    if not homepage_html:
        return []

    homepage_text = _extract_text(homepage_html)
    pages = [{"url": start_url, "text": homepage_text, "quality_tier": "primary_url"}]
    seen = {_normalize_url(start_url)}

    links = _collect_links(homepage_html, start_url)
    # High-signal pages first, then secondary
    links.sort(key=lambda l: (0 if l["quality_tier"] == "primary_url" else 1))

    for link in links:
        if len(pages) >= _MAX_PAGES:
            break
        norm = _normalize_url(link["url"])
        if norm in seen:
            continue
        seen.add(norm)

        html = _fetch_html(link["url"])
        if not html:
            continue
        text = _extract_text(html)
        if text:
            pages.append({"url": link["url"], "text": text, "quality_tier": link["quality_tier"]})
            print(f"[ingest]   fetched ({link['quality_tier']}) {link['url']}")

    return pages


def _collect_links(html: str, base_url: str) -> list[dict]:
    """Extract same-domain links from HTML, assigning quality tiers."""
    base_domain = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc != base_domain:
            continue
        if parsed.scheme not in ("http", "https"):
            continue

        path_parts = set(parsed.path.lower().strip("/").split("/"))
        tier = "primary_url" if path_parts & _HIGH_SIGNAL else "secondary_url"
        links.append({"url": full_url.split("#")[0], "quality_tier": tier})

    # Deduplicate while preserving order
    seen, unique = set(), []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique.append(link)
    return unique


def _fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[ingest]   skip {url}: {e}", file=sys.stderr)
        return None


def _extract_text(html: str) -> str:
    """Strip HTML tags, collapse whitespace, truncate."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = " ".join(text.split())
    return text[:_MAX_CHARS_PER_PAGE]


def _normalize_url(url: str) -> str:
    """Strip fragment and trailing slash for deduplication."""
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl().rstrip("/")


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _read_pdf(path: Path) -> str:
    if not _PDF_AVAILABLE:
        raise ImportError("pdfplumber is not installed. Run: pip install pdfplumber")
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)[:_MAX_CHARS_PER_PAGE]


# ---------------------------------------------------------------------------
# Core processing loop
# ---------------------------------------------------------------------------

def _process_pages(pages: list[dict], source_id: str) -> tuple[list[dict], list[str], int]:
    """
    For each page: extract facts via Claude, normalize domains, merge into knowledge.
    Returns (all_conflicts_resolved, domains_updated, total_facts_added).
    """
    all_conflicts: list[dict] = []
    domains_updated: list[str] = []
    facts_added = 0

    for page in pages:
        url_or_label = page["url"]
        print(f"[ingest]   extracting facts from {url_or_label}...")
        extracted = claude.extract_facts(page["text"], source_type=page["quality_tier"])
        print(f"[ingest]   extracted {len(extracted)} facts from {url_or_label}")
        if not extracted:
            continue

        for fact in extracted:
            domain = fact.get("domain", "misc")
            if domain not in DOMAINS:
                # Claude returned an invalid domain — reclassify
                domain = claude.classify_domain(fact.get("claim", ""))

            claim = fact.get("claim", "").strip()
            if not claim:
                continue

            result = knowledge.merge_fact(
                domain=domain,
                claim=claim,
                confidence=float(fact.get("confidence", 0.7)),
                confidence_reason=fact.get("confidence_reason", ""),
                source_id=source_id,
                quality_tier=page["quality_tier"],
                contradiction_checker=claude.detect_contradiction,
            )

            all_conflicts.extend(result["conflicts_resolved"])
            domains_updated.append(domain)
            facts_added += 1

            for question in fact.get("open_questions", []):
                if question:
                    knowledge.add_open_question(domain, question)

    return all_conflicts, domains_updated, facts_added


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_source_id() -> str:
    nums = []
    for p in SOURCES_DIR.glob("source_*.json"):
        try:
            nums.append(int(p.stem.split("_")[1]))
        except (IndexError, ValueError):
            pass
    return f"source_{(max(nums) + 1) if nums else 1:03d}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary(provenance: dict) -> dict:
    return {
        "source_id": provenance["source_id"],
        "pages_processed": len(provenance["pages_crawled"]),
        "facts_added": provenance["facts_added"],
        "conflicts_resolved": provenance["conflicts_resolved"],
        "domains_updated": provenance["domains_updated"],
    }


def _empty_summary(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "pages_processed": 0,
        "facts_added": 0,
        "conflicts_resolved": [],
        "domains_updated": [],
    }
