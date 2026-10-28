"""Runtime configuration, all from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional: load a local .env when present
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))


@dataclass(frozen=True)
class Settings:
    # Default: Google Gemini on its free tier. Any LangChain "provider:model" works, e.g. anthropic:claude-sonnet-5-5.
    model: str = os.getenv("MODEL", "google_genai:gemini-3.8-flash")
    fast_model: str = os.getenv("FAST_MODEL", "google_genai:gemini-3.5-flash-lite")
    tavily_key: str | None = os.getenv("TAVILY_API_KEY") or None
    composio_key: str | None = os.getenv("COMPOSIO_API_KEY") or None
    max_search_results: int = int(os.getenv("MAX_SEARCH_RESULTS", "6"))
    max_pages: int = int(os.getenv("MAX_PAGES", "10"))
    page_char_limit: int = int(os.getenv("PAGE_CHAR_LIMIT", "14000"))
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "15"))
    cache_days: int = int(os.getenv("GUIDE_CACHE_DAYS", "7"))
    # Parallel page-extraction calls. Keep low on free model tiers (requests-per-minute limits).
    extract_concurrency: int = int(os.getenv("EXTRACT_CONCURRENCY", "2"))
    user_agent: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (compatible; OAuthGuideAgent/1.0; +https://github.com/)",
    )
    curated_dir: Path = field(default_factory=lambda: DATA_DIR / "guides" / "curated")
    generated_dir: Path = field(default_factory=lambda: DATA_DIR / "guides" / "generated")
    catalog_path: Path = field(default_factory=lambda: DATA_DIR / "catalog.json")

    @property
    def llm_configured(self) -> bool:
        provider = self.model.split(":", 1)[0]
        envs = {
            "anthropic": ["ANTHROPIC_API_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "google_genai": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        }.get(provider)
        return envs is None or any(os.getenv(e) for e in envs)


settings = Settings()

# Composio's callback for custom (bring-your-own) OAuth apps. Confirmed against Composio docs
# by the research pass; see docs/VERIFICATION.md. Override if Composio changes it.
COMPOSIO_REDIRECT_URI = os.getenv(
    "COMPOSIO_REDIRECT_URI", "https://backend.composio.dev/api/v3/toolkits/auth/callback"
)
