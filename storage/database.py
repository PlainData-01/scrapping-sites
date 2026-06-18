"""SQLite para cache e histórico de sites rastreados."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

import aiosqlite

from config import CACHE_DAYS, DATABASE_PATH, SiteData

logger = logging.getLogger(__name__)


def _normalize_site_url(url: str) -> str:
    """Normaliza URL do site para chave de cache."""
    parsed = urlparse(url)
    netloc = parsed.netloc.replace("www.", "")
    return f"{parsed.scheme}://{netloc}"


async def init_database() -> None:
    """Cria tabelas se não existirem."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS crawled_sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                crawled_at TEXT NOT NULL,
                pages_found INTEGER DEFAULT 0,
                status TEXT DEFAULT 'completed',
                data_json TEXT
            );

            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                page_type TEXT,
                scraped_at TEXT NOT NULL,
                screenshot_path TEXT,
                FOREIGN KEY (site_id) REFERENCES crawled_sites(id)
            );

            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL,
                generated_at TEXT NOT NULL,
                pdf_path TEXT,
                email_sent INTEGER DEFAULT 0,
                FOREIGN KEY (site_id) REFERENCES crawled_sites(id)
            );
        """)
        await db.commit()


async def site_already_crawled(url: str) -> tuple[bool, dict | None]:
    """
    Verifica se o site foi rastreado nos últimos CACHE_DAYS dias.

    Retorna (bool, dados_cacheados ou None).
    """
    normalized = _normalize_site_url(url)
    cutoff = (datetime.now() - timedelta(days=CACHE_DAYS)).isoformat()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM crawled_sites WHERE url = ? AND crawled_at > ?",
            (normalized, cutoff),
        )
        row = await cursor.fetchone()

    if row and row["data_json"]:
        try:
            data = json.loads(row["data_json"])
            return True, data
        except json.JSONDecodeError:
            pass

    return False, None


async def save_site_data(site_data: SiteData) -> int:
    """Salva dados do site e retorna o ID do registro."""
    normalized = _normalize_site_url(site_data.url)
    now = datetime.now().isoformat()

    serializable = {
        "url": site_data.url,
        "domain": site_data.domain,
        "pages": site_data.pages,
        "assets": site_data.assets,
        "contacts": site_data.contacts,
        "colors": site_data.colors,
        "fonts": site_data.fonts,
        "seo_issues": site_data.seo_issues,
        "screenshots": site_data.screenshots,
        "analysis": site_data.analysis,
        "proposal_pdf_path": site_data.proposal_pdf_path,
        "email_content": site_data.email_content,
        "briefing_path": site_data.briefing_path,
        "site_project_path": site_data.site_project_path,
    }

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO crawled_sites (url, crawled_at, pages_found, status, data_json)
            VALUES (?, ?, ?, 'completed', ?)
            ON CONFLICT(url) DO UPDATE SET
                crawled_at = excluded.crawled_at,
                pages_found = excluded.pages_found,
                status = excluded.status,
                data_json = excluded.data_json
            """,
            (
                normalized,
                now,
                len(site_data.pages),
                json.dumps(serializable, ensure_ascii=False, default=str),
            ),
        )
        await db.commit()

        site_id_cursor = await db.execute(
            "SELECT id FROM crawled_sites WHERE url = ?", (normalized,)
        )
        site_row = await site_id_cursor.fetchone()
        site_id = site_row[0] if site_row else cursor.lastrowid

        for page in site_data.pages:
            await db.execute(
                """
                INSERT INTO pages (site_id, url, page_type, scraped_at, screenshot_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    site_id,
                    page.get("url", ""),
                    page.get("page_type", "other"),
                    now,
                    page.get("screenshot_path", ""),
                ),
            )

        if site_data.proposal_pdf_path:
            await db.execute(
                """
                INSERT INTO proposals (site_id, generated_at, pdf_path)
                VALUES (?, ?, ?)
                """,
                (site_id, now, site_data.proposal_pdf_path),
            )

        await db.commit()

    logger.info("Dados salvos para %s (id=%d)", normalized, site_id)
    return site_id
