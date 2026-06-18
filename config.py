"""Configurações globais, variáveis de ambiente e estruturas de dados do agente."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
MAX_PAGES_PER_SITE: int = int(os.getenv("MAX_PAGES_PER_SITE", "50"))
CRAWL_DELAY_SECONDS: float = float(os.getenv("CRAWL_DELAY_SECONDS", "1.5"))
OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", "./output"))
DATABASE_PATH: Path = Path(os.getenv("DATABASE_PATH", "./storage/scraping.db"))

CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
MAX_CONCURRENT_SCRAPERS: int = 3
CACHE_DAYS: int = 7

USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf", ".zip", ".rar", ".7z", ".exe", ".dmg",
        ".mp4", ".mp3", ".avi", ".mov", ".webm",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
        ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    }
)


@dataclass
class SiteData:
    """Dados consolidados de um site rastreado."""

    url: str
    pages: list[dict] = field(default_factory=list)
    assets: list[dict] = field(default_factory=list)
    contacts: dict = field(default_factory=dict)
    colors: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    seo_issues: list[str] = field(default_factory=list)
    screenshots: dict[str, str] = field(default_factory=dict)
    domain: str = ""
    analysis: dict | None = None
    proposal_pdf_path: str | None = None
    email_content: dict | None = None
    briefing_path: str | None = None
    site_project_path: str | None = None

    def __post_init__(self) -> None:
        if not self.domain:
            from urllib.parse import urlparse

            parsed = urlparse(self.url)
            self.domain = parsed.netloc.replace("www.", "")


def ensure_directories() -> None:
    """Garante que diretórios de saída existam."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
