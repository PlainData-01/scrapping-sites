"""
Camada de persistência com suporte a Supabase (preferido) e
SQLite local (fallback quando Supabase não configurado).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import aiosqlite

from config import CACHE_DAYS, DATABASE_PATH, SiteData
from storage.lead_utils import parse_json_field
from storage.supabase_client import get_supabase, supabase_disponivel

logger = logging.getLogger(__name__)

CACHE_VERSION = "2.0"


def _normalize_site_url(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.replace("www.", "")
    return f"{parsed.scheme}://{netloc}"


def _normalize_domain_key(domain: str) -> str:
    return domain.replace("_", ".").replace("www.", "").lower()


def _domain_from_row(url: str, data: dict) -> str:
    domain = data.get("domain", "")
    if domain:
        return domain.replace("www.", "")
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


def _site_row_to_cache_dict(row: dict) -> dict:
    analysis = row.get("analysis") or {}
    if isinstance(analysis, str):
        try:
            analysis = json.loads(analysis)
        except json.JSONDecodeError:
            analysis = {}
    cache_payload = analysis.pop("_cache_payload", {}) if isinstance(analysis, dict) else {}

    return {
        "cache_version": row.get("cache_version", CACHE_VERSION),
        "url": row.get("url", ""),
        "domain": row.get("domain", ""),
        "pages": row.get("pages") or cache_payload.get("pages", []),
        "assets": row.get("assets") or cache_payload.get("assets", []),
        "contacts": row.get("contacts") or {},
        "colors": row.get("colors") or [],
        "fonts": row.get("fonts") or [],
        "seo_issues": row.get("seo_issues") or [],
        "screenshots": row.get("screenshots") or cache_payload.get("screenshots", {}),
        "analysis": analysis or None,
        "proposal_pdf_path": row.get("proposal_pdf_path") or "",
        "email_content": row.get("email_content"),
        "briefing_path": row.get("briefing_path") or "",
        "site_project_path": row.get("site_project_path") or "",
    }


def _site_data_to_supabase_row(site_data: SiteData) -> dict:
    analysis = dict(site_data.analysis or {})
    cache_payload = {
        "pages": site_data.pages,
        "assets": site_data.assets,
        "screenshots": site_data.screenshots,
    }
    analysis["_cache_payload"] = cache_payload

    return {
        "url": _normalize_site_url(site_data.url),
        "domain": site_data.domain,
        "pages_count": len(site_data.pages),
        "assets_count": len(site_data.assets),
        "pages": site_data.pages,
        "assets": site_data.assets,
        "screenshots": site_data.screenshots,
        "contacts": site_data.contacts,
        "seo_issues": site_data.seo_issues,
        "colors": site_data.colors,
        "fonts": site_data.fonts,
        "analysis": analysis,
        "business_name": (site_data.analysis or {}).get("business_name", ""),
        "business_type": (site_data.analysis or {}).get("business_type", ""),
        "niche_category": (site_data.analysis or {}).get("niche_category", ""),
        "proposal_pdf_path": site_data.proposal_pdf_path or "",
        "briefing_path": str(site_data.briefing_path or ""),
        "site_project_path": site_data.site_project_path or "",
        "email_content": site_data.email_content,
        "cache_version": CACHE_VERSION,
        "status": "completed",
    }


def _extrair_coluna_ausente(exc: Exception) -> str | None:
    """Extrai nome da coluna ausente de erros PostgREST/PG."""
    import re

    msg = str(exc)
    for pattern in (
        r"Could not find the '(\w+)' column",
        r"column sites\.(\w+) does not exist",
        r"column leads\.(\w+) does not exist",
    ):
        match = re.search(pattern, msg)
        if match:
            return match.group(1)
    return None


def _supabase_update_resiliente(sb, tabela: str, data: dict, match_col: str, match_val: str):
    """Update removendo colunas ausentes no schema (compatível com legado)."""
    payload = dict(data)
    for _ in range(12):
        try:
            return sb.table(tabela).update(payload).eq(match_col, match_val).execute()
        except Exception as exc:
            coluna = _extrair_coluna_ausente(exc)
            if coluna and coluna in payload:
                logger.debug("Coluna '%s' ausente em %s — omitindo no update", coluna, tabela)
                payload.pop(coluna)
                continue
            raise
    raise RuntimeError(f"Update em {tabela} falhou após remover colunas opcionais")


def _supabase_upsert_resiliente(sb, tabela: str, data: dict, on_conflict: str):
    """Upsert removendo colunas ausentes no schema (compatível com v1)."""
    payload = dict(data)
    for _ in range(12):
        try:
            return sb.table(tabela).upsert(payload, on_conflict=on_conflict).execute()
        except Exception as exc:
            coluna = _extrair_coluna_ausente(exc)
            if coluna and coluna in payload:
                logger.debug("Coluna '%s' ausente em %s — omitindo", coluna, tabela)
                payload.pop(coluna)
                continue
            raise
    raise RuntimeError(f"Upsert em {tabela} falhou após remover colunas opcionais")


def _lead_dict_to_supabase(lead_data: dict) -> dict:
    from models.lead_status import normalize_status

    website = lead_data.get("website", "")
    domain = lead_data.get("domain") or urlparse(website).netloc.replace("www.", "")
    score_reasons = lead_data.get("score_reasons", [])
    if isinstance(score_reasons, str):
        try:
            score_reasons = json.loads(score_reasons)
        except json.JSONDecodeError:
            score_reasons = [score_reasons]
    commercial = lead_data.get("commercial_analysis") or {}
    if isinstance(commercial, str):
        try:
            commercial = json.loads(commercial)
        except json.JSONDecodeError:
            commercial = {}
    messages_pack = lead_data.get("messages_pack") or {}
    if isinstance(messages_pack, str):
        try:
            messages_pack = json.loads(messages_pack)
        except json.JSONDecodeError:
            messages_pack = {}

    crm = normalize_status(lead_data.get("crm_status") or lead_data.get("status_crm") or "new")

    main_pain = lead_data.get("main_pain") or lead_data.get("problema_principal", "")
    proc_status = lead_data.get("status", "pronto")

    return {
        "nome": lead_data.get("nome", ""),
        "domain": domain,
        "website": website,
        "endereco": lead_data.get("endereco", ""),
        "telefone": lead_data.get("telefone", lead_data.get("whatsapp", "")),
        "whatsapp": lead_data.get("whatsapp", ""),
        "whatsapp_link": lead_data.get("whatsapp_link", ""),
        "google_maps_url": lead_data.get("google_maps", lead_data.get("google_maps_url", "")),
        "avaliacao": float(lead_data.get("avaliacao") or 0),
        "total_avaliacoes": int(lead_data.get("total_avaliacoes") or 0),
        "categoria": lead_data.get("categoria", lead_data.get("niche", "")),
        "score": int(lead_data.get("opportunity_score") or lead_data.get("score") or 0),
        "plataforma": lead_data.get("plataforma_detectada", lead_data.get("plataforma", "")),
        "prioridade": lead_data.get("prioridade", "baixa"),
        "qualificado": bool(lead_data.get("qualificado", True)),
        "motivo_descarte": lead_data.get("motivo_descarte", ""),
        "problema_principal": main_pain,
        "mensagem_whatsapp": lead_data.get("mensagem_whatsapp", ""),
        "mensagem_completa": lead_data.get("mensagem_completa", lead_data.get("mensagem_consultiva", "")),
        "status_processamento": proc_status,
        "status": proc_status,
        "status_crm": crm,
        "prospectado_por": os.getenv("USUARIO", "usuario1"),
        "icp_id": lead_data.get("icp_id", "odontologia"),
        "score_reasons": score_reasons,
        "score_detalhes": score_reasons,
        "main_pain": main_pain,
        "commercial_angle": lead_data.get("commercial_angle", ""),
        "suggested_offer": lead_data.get("suggested_offer", ""),
        "commercial_analysis": commercial,
        "messages_pack": messages_pack,
    }


def _lead_row_to_api_dict(row: dict) -> dict:
    from storage.lead_utils import extract_city_neighborhood, parse_json_field, parse_json_list_field

    notas = parse_json_list_field(row.get("notas"), [])
    messages_pack = parse_json_field(row.get("messages_pack"), {})
    score_reasons = parse_json_list_field(
        row.get("score_reasons") if row.get("score_reasons") is not None else row.get("score_detalhes"),
        [],
    )
    commercial_analysis = parse_json_field(row.get("commercial_analysis"), {})
    city, neighborhood = extract_city_neighborhood(row.get("endereco", ""))

    return {
        "id": row.get("id"),
        "nome": row.get("nome", ""),
        "business_name": row.get("nome", ""),
        "website": row.get("website", ""),
        "website_url": row.get("website", ""),
        "domain": row.get("domain", ""),
        "endereco": row.get("endereco", ""),
        "city": city,
        "neighborhood": neighborhood,
        "telefone": row.get("telefone", ""),
        "phone": row.get("telefone", ""),
        "whatsapp": row.get("whatsapp", ""),
        "whatsapp_link": row.get("whatsapp_link", ""),
        "google_maps_url": row.get("google_maps_url", ""),
        "avaliacao": row.get("avaliacao", 0),
        "rating": row.get("avaliacao", 0),
        "total_avaliacoes": row.get("total_avaliacoes", 0),
        "reviews_count": row.get("total_avaliacoes", 0),
        "score": row.get("score", 0),
        "opportunity_score": row.get("score", 0),
        "prioridade": row.get("prioridade", "baixa"),
        "plataforma_detectada": row.get("plataforma", ""),
        "qualificado": row.get("qualificado", True),
        "motivo_descarte": row.get("motivo_descarte", ""),
        "problema_principal": row.get("problema_principal", ""),
        "main_pain": row.get("main_pain") or row.get("problema_principal", ""),
        "commercial_angle": row.get("commercial_angle", ""),
        "suggested_offer": row.get("suggested_offer", ""),
        "score_reasons": score_reasons,
        "icp_id": row.get("icp_id", "odontologia"),
        "niche": row.get("categoria", ""),
        "categoria": row.get("categoria", ""),
        "commercial_analysis": commercial_analysis,
        "messages_pack": messages_pack,
        "mensagem_whatsapp": row.get("mensagem_whatsapp", ""),
        "mensagem_completa": row.get("mensagem_completa", ""),
        "status": row.get("status_processamento") or row.get("status", "pronto"),
        "crm_status": row.get("status_crm", "new"),
        "abordado_em": row.get("abordado_em") or row.get("last_contacted_at") or "",
        "last_contacted_at": row.get("last_contacted_at") or row.get("abordado_em") or "",
        "next_follow_up_at": row.get("next_follow_up_at") or "",
        "notas": notas,
        "prospectado_por": row.get("prospectado_por", ""),
        "created_at": row.get("created_at", ""),
        "updated_at": row.get("updated_at", ""),
        "atividades": parse_json_list_field(row.get("activities"), [])
        or [n for n in notas if isinstance(n, dict) and n.get("tipo") == "atividade"],
    }


# ─── INICIALIZAÇÃO ────────────────────────────────────────────────


async def init_database() -> None:
    """Inicializa banco — Supabase (verifica conexão) ou SQLite."""
    if supabase_disponivel():
        try:
            sb = get_supabase()
            await asyncio.to_thread(
                lambda: sb.table("sites").select("id").limit(1).execute()
            )
            logger.info("✅ Supabase conectado — banco compartilhado ativo")
        except Exception as exc:
            logger.error("❌ Supabase configurado mas com erro: %s", exc)
            logger.warning("Verifique SUPABASE_URL e SUPABASE_KEY no .env")
    else:
        logger.info("SQLite local ativo (configure Supabase para modo multi-usuário)")
        await _init_sqlite()


# ─── SITES (interface pública) ────────────────────────────────────


async def save_site_data(site_data: SiteData) -> int:
    if supabase_disponivel():
        return await _save_site_supabase(site_data)
    return await _save_site_sqlite(site_data)


async def get_site_data(domain: str) -> SiteData | None:
    if supabase_disponivel():
        return await _get_site_supabase(domain)
    return await _get_site_sqlite(domain)


async def site_already_crawled(url: str) -> tuple[bool, dict | None]:
    if supabase_disponivel():
        return await _check_cache_supabase(url)
    return await _check_cache_sqlite(url)


async def get_all_sites() -> list[dict]:
    if supabase_disponivel():
        return await _get_all_supabase()
    return await _get_all_sqlite()


async def get_site_email(domain: str) -> dict | None:
    if supabase_disponivel():
        return await _get_site_email_supabase(domain)
    return await _get_site_email_sqlite(domain)


# ─── LEADS (interface pública) ────────────────────────────────────


async def save_lead(lead_data: dict) -> int:
    if supabase_disponivel():
        return await _save_lead_supabase(lead_data)
    return await _save_lead_local(lead_data)


async def get_all_leads() -> list[dict]:
    if supabase_disponivel():
        return await _get_leads_supabase()
    return await _get_leads_local()


async def update_lead_status(domain: str, status: str, nota: str = "") -> bool:
    if supabase_disponivel():
        return await _update_lead_supabase(domain, status, nota)
    return await _update_lead_local(domain, status, nota)


async def get_lead_statuses() -> dict[str, dict]:
    if supabase_disponivel():
        return await _get_lead_statuses_supabase()
    return await _get_lead_statuses_local()


async def add_lead_note(domain: str, nota: str) -> list:
    if supabase_disponivel():
        return await _add_lead_note_supabase(domain, nota)
    return await _add_lead_note_local(domain, nota)


async def get_lead_notes() -> dict[str, list]:
    if supabase_disponivel():
        return await _get_lead_notes_supabase()
    return await _get_lead_notes_local()


async def append_lead_activity(domain: str, entry: dict) -> list:
    if supabase_disponivel():
        return await _append_lead_activity_supabase(domain, entry)
    return []


async def get_lead_activities(domain: str) -> list:
    if supabase_disponivel():
        return await _get_lead_activities_supabase(domain)
    return []


# ─── SUPABASE — SITES ─────────────────────────────────────────────


async def _save_site_supabase(site_data: SiteData) -> int:
    sb = get_supabase()
    data = _site_data_to_supabase_row(site_data)

    def _upsert():
        return _supabase_upsert_resiliente(sb, "sites", data, "url")

    result = await asyncio.to_thread(_upsert)
    site_id = result.data[0]["id"] if result.data else 0
    logger.info("Dados salvos no Supabase para %s (id=%s)", data["url"], site_id)
    return site_id


async def _get_site_supabase(domain: str) -> SiteData | None:
    sb = get_supabase()
    key = _normalize_domain_key(domain)

    def _fetch():
        return sb.table("sites").select("*").eq("domain", key).limit(1).execute()

    result = await asyncio.to_thread(_fetch)
    if not result.data:
        return None
    row = result.data[0]
    cache = _site_row_to_cache_dict(row)
    return SiteData(
        url=cache.get("url", row["url"]),
        domain=row.get("domain", key),
        pages=cache.get("pages", []),
        assets=cache.get("assets", []),
        contacts=cache.get("contacts", {}),
        colors=cache.get("colors", []),
        fonts=cache.get("fonts", []),
        seo_issues=cache.get("seo_issues", []),
        screenshots=cache.get("screenshots", {}),
        analysis=cache.get("analysis"),
        proposal_pdf_path=cache.get("proposal_pdf_path") or None,
        email_content=cache.get("email_content"),
        briefing_path=cache.get("briefing_path") or None,
        site_project_path=cache.get("site_project_path") or None,
    )


async def _check_cache_supabase(url: str) -> tuple[bool, dict | None]:
    domain = urlparse(url).netloc.replace("www.", "")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)).isoformat()
    sb = get_supabase()

    def _fetch():
        return (
            sb.table("sites")
            .select("*")
            .eq("domain", domain)
            .eq("cache_version", CACHE_VERSION)
            .gte("updated_at", cutoff)
            .limit(1)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    if result.data:
        return True, _site_row_to_cache_dict(result.data[0])
    return False, None


async def _get_all_supabase() -> list[dict]:
    sb = get_supabase()

    def _fetch():
        return (
            sb.table("sites")
            .select("*")
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    sites: list[dict] = []
    for row in result.data or []:
        domain = row.get("domain", "")
        domain_slug = domain.replace(".", "_")
        analysis_raw = row.get("analysis") or {}
        if isinstance(analysis_raw, str):
            try:
                analysis_raw = json.loads(analysis_raw)
            except json.JSONDecodeError:
                analysis_raw = {}
        analysis = dict(analysis_raw) if isinstance(analysis_raw, dict) else {}
        analysis.pop("_cache_payload", None)
        email = row.get("email_content")
        briefing_path = row.get("briefing_path") or ""
        site_path = row.get("site_project_path") or ""
        site_dir = Path(site_path) if site_path else None
        has_site = bool(site_dir and site_dir.exists())
        build_ok = bool(has_site and (site_dir / ".next").exists())

        sites.append({
            "domain": domain,
            "domain_slug": domain_slug,
            "url": row.get("url", ""),
            "business_name": analysis.get("business_name", domain),
            "business_type": analysis.get("business_type", ""),
            "crawled_at": row.get("updated_at") or row.get("created_at", ""),
            "pages_found": row.get("pages_count", 0),
            "status": row.get("status", "completed"),
            "has_email": bool(email),
            "has_briefing": bool(briefing_path) and Path(briefing_path).exists(),
            "has_site": has_site,
            "build_ok": build_ok,
            "seo_issues_count": len(row.get("seo_issues") or []),
            "contacts": row.get("contacts") or {},
            "seo_issues": (row.get("seo_issues") or [])[:10],
            "analysis": analysis,
            "assets_count": row.get("assets_count", 0),
            "site_project_path": site_path,
        })
    return sites


async def _get_site_email_supabase(domain: str) -> dict | None:
    site = await _get_site_supabase(domain)
    if site and isinstance(site.email_content, dict):
        return site.email_content
    return None


# ─── SUPABASE — LEADS ─────────────────────────────────────────────


async def _save_lead_supabase(lead_data: dict) -> int:
    sb = get_supabase()
    data = _lead_dict_to_supabase(lead_data)

    def _upsert():
        return _supabase_upsert_resiliente(sb, "leads", data, "domain")

    result = await asyncio.to_thread(_upsert)
    return result.data[0]["id"] if result.data else 0


async def _get_leads_supabase() -> list[dict]:
    sb = get_supabase()

    def _fetch():
        return (
            sb.table("leads")
            .select("*")
            .order("score", desc=True)
            .limit(500)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    return [_lead_row_to_api_dict(row) for row in (result.data or [])]


async def _update_lead_supabase(domain: str, status: str, nota: str = "") -> bool:
    from models.lead_status import normalize_status

    sb = get_supabase()
    key = _normalize_domain_key(domain)
    normalized = normalize_status(status)
    update_data: dict = {"status_crm": normalized}
    now = datetime.now(timezone.utc).isoformat()

    if normalized in ("contacted", "abordado"):
        update_data["abordado_em"] = now
        update_data["last_contacted_at"] = now
    elif normalized in ("interested", "interessado", "prototype_sent", "proposal_sent"):
        update_data["interessado_em"] = now
    elif normalized in ("closed", "fechado"):
        update_data["fechado_em"] = now
    elif normalized == "follow_up_later":
        update_data["next_follow_up_at"] = now

    if nota:
        row = await _fetch_lead_by_domain(key)
        notas = parse_json_field(row.get("notas") if row else None, [])
        notas.append({"texto": nota, "criado_em": now})
        update_data["notas"] = notas

    def _update():
        return _supabase_update_resiliente(sb, "leads", update_data, "domain", key)

    result = await asyncio.to_thread(_update)
    return bool(result.data)


async def _fetch_lead_by_domain(domain: str) -> dict | None:
    sb = get_supabase()

    def _fetch():
        return sb.table("leads").select("*").eq("domain", domain).limit(1).execute()

    result = await asyncio.to_thread(_fetch)
    return result.data[0] if result.data else None


async def _get_lead_statuses_supabase() -> dict[str, dict]:
    sb = get_supabase()

    def _fetch():
        return (
            sb.table("leads")
            .select("domain, status_crm, abordado_em, updated_at")
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    statuses: dict[str, dict] = {}
    for row in result.data or []:
        statuses[row["domain"]] = {
            "status": row.get("status_crm", "new"),
            "abordado_em": row.get("abordado_em") or "",
            "updated_at": row.get("updated_at") or "",
        }
    return statuses


async def _add_lead_note_supabase(domain: str, nota: str) -> list:
    key = _normalize_domain_key(domain)
    nota = nota.strip()
    if not nota:
        row = await _fetch_lead_by_domain(key)
        return parse_json_field(row.get("notas") if row else None, [])

    row = await _fetch_lead_by_domain(key)
    notas = parse_json_field(row.get("notas") if row else None, [])
    notas.append({"texto": nota, "criado_em": datetime.now(timezone.utc).isoformat()})

    sb = get_supabase()

    def _update():
        return sb.table("leads").update({"notas": notas}).eq("domain", key).execute()

    await asyncio.to_thread(_update)
    return notas


async def _append_lead_activity_supabase(domain: str, entry: dict) -> list:
    from storage.lead_utils import parse_json_field

    key = _normalize_domain_key(domain)
    row = await _fetch_lead_by_domain(key)
    if not row:
        return []
    activities = parse_json_field(row.get("activities"), [])
    activities.append(entry)
    activities = activities[-200:]

    sb = get_supabase()

    def _update():
        try:
            return sb.table("leads").update({"activities": activities}).eq("domain", key).execute()
        except Exception as exc:
            coluna = _extrair_coluna_ausente(exc)
            if coluna != "activities":
                raise
            notas = parse_json_field(row.get("notas"), [])
            notas.append({"tipo": "atividade", **entry})
            return sb.table("leads").update({"notas": notas[-200:]}).eq("domain", key).execute()

    await asyncio.to_thread(_update)
    return activities


async def _get_lead_activities_supabase(domain: str) -> list:
    from storage.lead_utils import parse_json_field

    row = await _fetch_lead_by_domain(_normalize_domain_key(domain))
    if not row:
        return []
    activities = parse_json_field(row.get("activities"), [])
    if activities:
        return activities
    notas = parse_json_field(row.get("notas"), [])
    return [n for n in notas if isinstance(n, dict) and n.get("tipo") == "atividade"]


async def _get_lead_notes_supabase() -> dict[str, list]:
    sb = get_supabase()

    def _fetch():
        return sb.table("leads").select("domain, notas").execute()

    result = await asyncio.to_thread(_fetch)
    notes: dict[str, list] = {}
    for row in result.data or []:
        notas = row.get("notas") or []
        if notas:
            notes[row["domain"]] = notas
    return notes


# ─── SQLITE — FALLBACK ────────────────────────────────────────────


async def _init_sqlite() -> None:
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


async def _check_cache_sqlite(url: str) -> tuple[bool, dict | None]:
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
            if data.get("cache_version") != CACHE_VERSION:
                logger.info(
                    "Cache desatualizado (v%s → v%s), reprocessando",
                    data.get("cache_version"), CACHE_VERSION,
                )
                return False, None
            return True, data
        except json.JSONDecodeError:
            pass

    return False, None


async def _save_site_sqlite(site_data: SiteData) -> int:
    normalized = _normalize_site_url(site_data.url)
    now = datetime.now().isoformat()

    serializable = {
        "cache_version": CACHE_VERSION,
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


async def _get_all_sqlite() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM crawled_sites ORDER BY crawled_at DESC"
        )
        rows = await cursor.fetchall()

    sites: list[dict] = []
    for row in rows:
        try:
            data = json.loads(row["data_json"]) if row["data_json"] else {}
        except json.JSONDecodeError:
            data = {}

        domain = _domain_from_row(row["url"], data)
        domain_slug = domain.replace(".", "_")
        analysis = data.get("analysis") or {}
        email = data.get("email_content")
        briefing_path = data.get("briefing_path") or ""
        site_path = data.get("site_project_path") or ""
        site_dir = Path(site_path) if site_path else None

        has_site = bool(site_dir and site_dir.exists())
        build_ok = bool(has_site and (site_dir / ".next").exists())

        sites.append({
            "domain": domain,
            "domain_slug": domain_slug,
            "url": row["url"],
            "business_name": analysis.get("business_name", domain),
            "business_type": analysis.get("business_type", ""),
            "crawled_at": row["crawled_at"],
            "pages_found": row["pages_found"],
            "status": row["status"],
            "has_email": bool(email),
            "has_briefing": bool(briefing_path) and Path(briefing_path).exists(),
            "has_site": has_site,
            "build_ok": build_ok,
            "seo_issues_count": len(data.get("seo_issues") or []),
            "contacts": data.get("contacts") or {},
            "seo_issues": (data.get("seo_issues") or [])[:10],
            "analysis": analysis,
            "assets_count": len(data.get("assets") or []),
            "site_project_path": site_path,
        })

    return sites


async def _get_site_email_sqlite(domain: str) -> dict | None:
    key = _normalize_domain_key(domain)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT url, data_json FROM crawled_sites")
        rows = await cursor.fetchall()

    for row in rows:
        try:
            data = json.loads(row["data_json"]) if row["data_json"] else {}
        except json.JSONDecodeError:
            continue
        stored = _normalize_domain_key(_domain_from_row(row["url"], data))
        if stored == key:
            email = data.get("email_content")
            return email if isinstance(email, dict) else None

    return None


async def _get_site_sqlite(domain: str) -> SiteData | None:
    key = _normalize_domain_key(domain)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT url, data_json FROM crawled_sites")
        rows = await cursor.fetchall()

    for row in rows:
        try:
            data = json.loads(row["data_json"]) if row["data_json"] else {}
        except json.JSONDecodeError:
            continue
        stored = _normalize_domain_key(_domain_from_row(row["url"], data))
        if stored != key:
            continue
        return SiteData(
            url=data.get("url", row["url"]),
            domain=_domain_from_row(row["url"], data),
            pages=data.get("pages", []),
            assets=data.get("assets", []),
            contacts=data.get("contacts", {}),
            colors=data.get("colors", []),
            fonts=data.get("fonts", []),
            seo_issues=data.get("seo_issues", []),
            screenshots=data.get("screenshots", {}),
            analysis=data.get("analysis"),
            proposal_pdf_path=data.get("proposal_pdf_path"),
            email_content=data.get("email_content"),
            briefing_path=data.get("briefing_path"),
            site_project_path=data.get("site_project_path"),
        )

    return None


async def _save_lead_local(lead_data: dict) -> int:
    """Fallback local: leads ficam no CSV (pipeline) — noop retorna 0."""
    return 0


async def _get_leads_local() -> list[dict]:
    return []


async def _update_lead_local(domain: str, status: str, nota: str = "") -> bool:
    from prospector.leads_crm import atualizar_status, adicionar_nota

    key = _normalize_domain_key(domain)
    try:
        atualizar_status(key, status)
        if nota:
            adicionar_nota(key, nota)
        return True
    except ValueError:
        return False


async def _get_lead_statuses_local() -> dict[str, dict]:
    from prospector.leads_crm import ler_status_todos

    return ler_status_todos()


async def _add_lead_note_local(domain: str, nota: str) -> list:
    from prospector.leads_crm import adicionar_nota

    return adicionar_nota(_normalize_domain_key(domain), nota)


async def _get_lead_notes_local() -> dict[str, list]:
    from prospector.leads_crm import ler_notas_todos

    return ler_notas_todos()
