from pathlib import Path

# Fixed domain set — facts that don't fit land in "misc"
DOMAINS = ["company_overview", "products", "pricing", "team", "technology", "misc"]

# Higher number = higher authority in conflict resolution
QUALITY_TIERS: dict[str, int] = {
    "primary_url": 3,
    "document": 2,
    "secondary_url": 1,
    "conversation": 0,
}

# Keyword → domain routing used by retrieval and domain fallback pre-filter
KEYWORD_MAP: dict[str, str] = {
    # pricing
    "price": "pricing", "cost": "pricing", "plan": "pricing",
    "plans": "pricing", "tier": "pricing", "tiers": "pricing",
    "billing": "pricing", "subscription": "pricing", "paid": "pricing",
    "free": "pricing", "enterprise": "pricing", "revenue": "pricing",
    # products
    "feature": "products", "features": "products", "product": "products",
    "integration": "products", "integrations": "products", "api": "products",
    "functionality": "products", "capability": "products", "capabilities": "products",
    "tool": "products", "tools": "products", "workflow": "products",
    "use case": "products", "demo": "products",
    # team
    "founder": "team", "ceo": "team", "cto": "team", "coo": "team",
    "team": "team", "employee": "team", "employees": "team",
    "staff": "team", "leadership": "team", "hire": "team",
    "headcount": "team", "people": "team",
    # company_overview
    "mission": "company_overview", "about": "company_overview",
    "company": "company_overview", "founded": "company_overview",
    "headquarters": "company_overview", "hq": "company_overview",
    "vision": "company_overview", "industry": "company_overview",
    "startup": "company_overview", "history": "company_overview",
    # technology
    "stack": "technology", "tech": "technology", "architecture": "technology",
    "infrastructure": "technology", "platform": "technology",
    "language": "technology", "framework": "technology",
    "database": "technology", "cloud": "technology", "built": "technology",
    "open source": "technology", "sdk": "technology",
}

TOKEN_BUDGET = 3000          # max tokens of knowledge context per prompt
SESSION_WINDOW = 8           # max turns kept in session_history.json
CONFLICT_CONFIDENCE_CAP = 0.6  # applied to both sides when a conflict is resolved
CHARS_PER_TOKEN = 4          # rough estimate for token budgeting

MEMORY_DIR = Path("memory")
KNOWLEDGE_DIR = MEMORY_DIR / "knowledge"
WORKING_DIR = MEMORY_DIR / "working"
SOURCES_DIR = MEMORY_DIR / "sources"
