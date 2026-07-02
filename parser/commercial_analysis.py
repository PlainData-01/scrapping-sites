"""Análise comercial simples de sites para prospecção."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from config import SiteData


@dataclass
class SiteCommercialAnalysis:
    has_visible_whatsapp: bool = False
    has_whatsapp_above_fold: bool = False
    has_clear_cta: bool = False
    has_contact_form: bool = False
    has_service_pages: bool = False
    has_social_proof: bool = False
    has_visible_phone: bool = False
    has_google_analytics: bool = False
    has_google_tag_manager: bool = False
    has_meta_pixel: bool = False
    has_title: bool = False
    has_meta_description: bool = False
    has_h1: bool = False
    old_visual_site: bool = False
    weak_mobile_cta: bool = False
    broken_links_count: int = 0
    commercial_issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_WHATSAPP_PATTERNS = [
    r"wa\.me/",
    r"api\.whatsapp\.com",
    r"whatsapp",
    r"btn-whatsapp",
    r"floating-whatsapp",
]

_CTA_PATTERNS = [
    r"agendar",
    r"agende",
    r"orçamento",
    r"contato",
    r"fale conosco",
    r"reserve",
    r"peça já",
    r"chamar no whatsapp",
]

_FORM_PATTERNS = [
    r"<form\b",
    r"type=[\"']email[\"']",
    r"contact-form",
    r"formulário",
]

_SOCIAL_PROOF_PATTERNS = [
    r"depoimento",
    r"avaliação",
    r"testemunho",
    r"o que dizem",
    r"clientes satisfeitos",
    r"google reviews",
    r"\d+\s*estrelas",
]

_SERVICE_PAGE_TYPES = {"service", "services", "treatment", "procedures", "pricing"}


def analyze_site_commercial(site_data: SiteData) -> SiteCommercialAnalysis:
    """Detecta sinais comerciais úteis para venda a partir do HTML raspado."""
    result = SiteCommercialAnalysis()
    all_html = ""
    home_html = ""

    for page in site_data.pages:
        html = (page.get("html") or "").lower()
        all_html += html
        url = (page.get("url") or "").lower()
        if url.rstrip("/") in (site_data.url.rstrip("/"), site_data.url.rstrip("/") + "/"):
            home_html = html
        page_type = (page.get("page_type") or "").lower()
        if page_type in _SERVICE_PAGE_TYPES:
            result.has_service_pages = True

    if not home_html and site_data.pages:
        home_html = (site_data.pages[0].get("html") or "").lower()

    contacts = site_data.contacts or {}
    if contacts.get("whatsapp") or contacts.get("phones"):
        result.has_visible_whatsapp = True
    for pat in _WHATSAPP_PATTERNS:
        if re.search(pat, home_html or all_html, re.I):
            result.has_visible_whatsapp = True
            if home_html and re.search(pat, home_html, re.I):
                # Heurística: primeiros 15k chars ≈ above fold
                if re.search(pat, home_html[:15000], re.I):
                    result.has_whatsapp_above_fold = True
            break

    for pat in _CTA_PATTERNS:
        if re.search(pat, home_html[:20000] if home_html else all_html[:20000], re.I):
            result.has_clear_cta = True
            break

    if not result.has_clear_cta and not result.has_whatsapp_above_fold:
        result.weak_mobile_cta = True

    for pat in _FORM_PATTERNS:
        if re.search(pat, all_html, re.I):
            result.has_contact_form = True
            break

    for pat in _SOCIAL_PROOF_PATTERNS:
        if re.search(pat, all_html, re.I):
            result.has_social_proof = True
            break

    if contacts.get("phones"):
        result.has_visible_phone = True
    elif re.search(r"\(\d{2}\)\s*\d{4,5}[- ]?\d{4}", all_html):
        result.has_visible_phone = True

    if "google-analytics.com" in all_html or "gtag(" in all_html or "ga(" in all_html:
        result.has_google_analytics = True
    if "googletagmanager.com" in all_html or "gtm.js" in all_html:
        result.has_google_tag_manager = True
    if "connect.facebook.net" in all_html or "fbq(" in all_html:
        result.has_meta_pixel = True

    # SEO básico na home
    for page in site_data.pages[:3]:
        parsed = page.get("parsed") or {}
        if parsed.get("title"):
            result.has_title = True
        if parsed.get("meta_description"):
            result.has_meta_description = True
        if parsed.get("h1"):
            result.has_h1 = True

    # Visual antigo — heurísticas simples
    old_markers = ["table layout", "comic sans", "visitor counter", "flash", "marquee"]
    platform = (site_data.analysis or {}).get("platform", "").lower()
    if platform in ("wix", "hostinger", "duda") or any(m in all_html for m in old_markers):
        result.old_visual_site = True

    result.broken_links_count = _count_simple_broken_links(site_data)
    result.commercial_issues = _build_issues(result, site_data)
    result.recommendations = _build_recommendations(result)
    return result


def _count_simple_broken_links(site_data: SiteData) -> int:
    """Conta links internos que retornam erro (heurística leve)."""
    count = 0
    for page in site_data.pages:
        for issue in page.get("seo_issues") or []:
            if "link quebrado" in issue.lower() or "404" in issue.lower():
                count += 1
    return count


def _build_issues(result: SiteCommercialAnalysis, site_data: SiteData) -> list[str]:
    issues: list[str] = []
    if result.weak_mobile_cta:
        issues.append("CTA para WhatsApp não aparece de forma clara acima da dobra.")
    if not result.has_meta_pixel and not result.has_google_tag_manager:
        issues.append("Não encontramos Meta Pixel ou GTM para medição de conversão.")
    if not result.has_service_pages:
        issues.append("Pouca ou nenhuma página dedicada a serviços/procedimentos.")
    if not result.has_social_proof:
        issues.append("Site sem seção clara de prova social ou depoimentos.")
    if not result.has_contact_form:
        issues.append("Sem formulário de contato visível.")
    if not result.has_h1:
        issues.append("Página inicial sem H1 claro.")
    if site_data.seo_issues:
        for issue in site_data.seo_issues[:2]:
            text = issue.split("] ", 1)[-1] if "] " in issue else issue
            if text not in issues:
                issues.append(text)
    return issues[:5]


def _build_recommendations(result: SiteCommercialAnalysis) -> list[str]:
    recs: list[str] = []
    if result.weak_mobile_cta:
        recs.append("Adicionar botão fixo de WhatsApp visível no mobile.")
    if not result.has_service_pages:
        recs.append("Criar seções ou páginas por serviço/procedimento principal.")
    if not result.has_social_proof:
        recs.append("Incluir depoimentos e avaliações do Google na página.")
    if not result.has_meta_pixel:
        recs.append("Instalar pixel de conversão para medir resultados.")
    if result.old_visual_site:
        recs.append("Modernizar layout com foco em conversão e credibilidade.")
    if not recs:
        recs.append("Otimizar hierarquia visual e CTA principal na home.")
    return recs[:3]
