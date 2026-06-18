"""Parser de HTML para dados estruturados e detecção de problemas de SEO."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
PHONE_PATTERN = re.compile(
    r"(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}[-.\s]?\d{4}"
)
WA_ME_PATTERN = re.compile(r"wa\.me\/(\d{10,13})")
HTML_PHONE_PATTERN = re.compile(
    r"(?:\+55[\s-]?)?(?:\(?\d{2}\)?[\s-]?)(?:9[\s-]?)?\d{4}[\s-]?\d{4}"
)

SYSTEM_EMAIL_BLOCKLIST = ("jquery", "wordpress", "elementor", "google", "schema")

SERVICOS_KEYWORDS = [
    "invisalign", "ortodontia", "aparelho", "alinhadores", "clareamento",
    "implante", "protese", "cirurgia", "ortognatica", "periodontia",
    "gengiva", "bruxismo", "atm", "dores", "disfuncao", "apneia",
    "ronco", "polissonografia", "pediatria", "crianca", "clinica-geral",
    "restauracao", "extracao", "canal", "endodontia",
]


def detect_page_type(url: str, title: str = "", h1: str = "") -> str:
    """Detecta o tipo de página pela URL e conteúdo."""
    path = urlparse(url).path.strip("/").lower()

    if path == "" or path == "/":
        return "home"

    if any(x in path for x in ["contato", "telefone", "contact", "fale-conosco"]):
        return "contato"

    if any(x in path for x in [
        "sobre", "sobre-nos", "about", "quem-somos",
        "a-clinica", "nossa-historia",
    ]):
        return "sobre"

    if any(x in path for x in [
        "blog", "dicas", "artigos", "noticias", "post", "novidades",
    ]):
        return "blog"

    if any(x in path for x in ["tratamentos", "servicos", "especialidades"]):
        return "servicos"

    if any(x in path for x in SERVICOS_KEYWORDS):
        return "servico"

    title_lower = title.lower()
    h1_lower = h1.lower()
    if any(x in title_lower or x in h1_lower for x in ["contato", "fale conosco"]):
        return "contato"
    if any(x in title_lower or x in h1_lower for x in ["sobre", "quem somos"]):
        return "sobre"

    if path and "/" not in path:
        return "servico"

    return "other"


def extract_contacts(html: str) -> dict:
    """Extrai contatos do HTML fonte via regex (WhatsApp, telefones, emails)."""
    contacts: dict = {}

    wa_matches = WA_ME_PATTERN.findall(html)
    if wa_matches:
        num = wa_matches[0]
        if num.startswith("55") and len(num) >= 12:
            contacts["whatsapp"] = f"+{num}"
        elif len(num) in (10, 11):
            contacts["whatsapp"] = f"+55{num}"
        else:
            contacts["whatsapp"] = f"+{num}"

    html_no_wa = WA_ME_PATTERN.sub("", html)
    phones = HTML_PHONE_PATTERN.findall(html_no_wa)
    if phones:
        contacts["telefones"] = list(dict.fromkeys(phones[:5]))

    emails = EMAIL_PATTERN.findall(html)
    real_emails = [
        e for e in emails
        if not any(x in e.lower() for x in SYSTEM_EMAIL_BLOCKLIST)
    ]
    if real_emails:
        contacts["emails"] = list(dict.fromkeys(real_emails[:3]))

    return contacts


def _extract_sections(soup: BeautifulSoup) -> list[dict]:
    """Extrai texto limpo por seção semântica."""
    sections: list[dict] = []
    semantic_tags = ["header", "main", "section", "article", "aside"]

    for tag_name in semantic_tags:
        for tag in soup.find_all(tag_name):
            text = tag.get_text(separator=" ", strip=True)
            if len(text) > 50:
                sections.append({
                    "tag": tag_name,
                    "heading": _section_heading(tag),
                    "text": text[:2000],
                })

    if not sections:
        body = soup.find("body")
        if body:
            text = body.get_text(separator=" ", strip=True)
            if text:
                sections.append({"tag": "body", "heading": "", "text": text[:3000]})

    return sections


def _section_heading(tag) -> str:
    """Extrai heading principal de uma seção."""
    for h in tag.find_all(["h1", "h2", "h3"], recursive=False):
        return h.get_text(strip=True)
    child_h = tag.find(["h1", "h2", "h3"])
    return child_h.get_text(strip=True) if child_h else ""


def _detect_seo_issues(soup: BeautifulSoup, url: str) -> list[str]:
    """Detecta problemas óbvios de SEO."""
    issues: list[str] = []

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if not meta_desc or not meta_desc.get("content", "").strip():
        issues.append("Ausência de meta description")

    h1_tags = soup.find_all("h1")
    if not h1_tags:
        issues.append("H1 ausente na página")
    elif len(h1_tags) > 1:
        issues.append(f"Múltiplos H1s detectados ({len(h1_tags)})")

    title_tag = soup.find("title")
    if not title_tag or not title_tag.get_text(strip=True):
        issues.append("Title tag ausente")
    elif len(title_tag.get_text(strip=True)) > 60:
        issues.append("Title tag muito longa (>60 caracteres)")

    images_no_alt = [
        img for img in soup.find_all("img")
        if not img.get("alt", "").strip()
    ]
    if images_no_alt:
        issues.append(f"{len(images_no_alt)} imagem(ns) sem alt text")

    body_text = soup.get_text(separator=" ", strip=True)
    word_count = len(body_text.split())
    if word_count < 300:
        issues.append(f"Texto muito curto na página ({word_count} palavras)")

    return issues


def _calculate_seo_score(issues: list[str]) -> int:
    """Calcula score de SEO de 0 a 100."""
    penalties = {
        "Ausência de meta description": 15,
        "H1 ausente na página": 20,
        "Múltiplos H1s detectados": 15,
        "Title tag ausente": 20,
        "Title tag muito longa": 10,
        "imagens sem alt text": 10,
        "Texto muito curto": 15,
    }
    score = 100
    for issue in issues:
        for key, penalty in penalties.items():
            if key in issue:
                score -= penalty
                break
    return max(0, score)


def _extract_addresses(soup: BeautifulSoup) -> list[str]:
    """Extrai endereços físicos do HTML parseado."""
    addresses: list[str] = []
    for tag in soup.find_all(["address", "p", "div", "span"]):
        classes = " ".join(tag.get("class", []))
        if any(kw in classes.lower() for kw in ["address", "contato", "localiz"]):
            addr_text = tag.get_text(strip=True)
            if len(addr_text) > 10:
                addresses.append(addr_text)
    return addresses


def _merge_page_contacts(html_contacts: dict, addresses: list[str]) -> dict:
    """Mescla contatos extraídos do HTML fonte com endereços do soup."""
    merged: dict = {
        "emails": html_contacts.get("emails", []),
        "phones": html_contacts.get("telefones", []),
        "telefones": html_contacts.get("telefones", []),
        "addresses": addresses,
        "whatsapp": html_contacts.get("whatsapp", ""),
        "telefone": html_contacts.get("telefones", [""])[0] if html_contacts.get("telefones") else "",
    }
    return merged


def parse_page_data(raw_html: str, url: str) -> dict:
    """
    Parseia HTML bruto e retorna dados estruturados com análise de SEO.

    Remove tags irrelevantes e identifica tipo de página.
    """
    soup = BeautifulSoup(raw_html, "lxml")

    for tag in soup.find_all(["script", "style", "nav", "footer", "iframe", "svg"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    h1_tag = soup.find("h1")
    h1_text = h1_tag.get_text(strip=True) if h1_tag else ""

    page_type = detect_page_type(url, title, h1_text)
    sections = _extract_sections(soup)
    seo_issues = _detect_seo_issues(soup, url)
    seo_score = _calculate_seo_score(seo_issues)

    html_contacts = extract_contacts(raw_html)
    addresses = _extract_addresses(soup)
    contacts = _merge_page_contacts(html_contacts, addresses)

    return {
        "url": url,
        "page_type": page_type,
        "sections": sections,
        "seo_score": seo_score,
        "seo_issues": seo_issues,
        "contacts": contacts,
        "word_count": len(soup.get_text(separator=" ", strip=True).split()),
    }
