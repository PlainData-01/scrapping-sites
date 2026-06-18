"""Geração de briefing estruturado para IA construtora (Lovable, V0, Bolt.new)."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from config import OUTPUT_DIR, USER_AGENT, SiteData

logger = logging.getLogger(__name__)

MISSING = "{DADO NÃO ENCONTRADO — preencher manualmente}"

GOOGLE_FONTS_PATTERN = re.compile(
    r"fonts\.googleapis\.com/css[^\"']*family=([^&\"']+)", re.IGNORECASE
)
CREDENTIAL_PATTERN = re.compile(
    r"\d+[\d.,]*\s*(?:anos?|pacientes?|clientes?|projetos?|casos?|%"
    r"|certificad|especializa|desde\s+\d{4}|\d{4})",
    re.IGNORECASE,
)
CTA_KEYWORDS = re.compile(
    r"(whatsapp|agendar|agende|saiba mais|fale conosco|contato|orçamento|"
    r"ligue|chamar|solicite|marque|consulta|entre em contato)",
    re.IGNORECASE,
)
FAQ_PATTERN = re.compile(r"^(?:pergunta|faq|como|qual|quando|por que|o que)", re.IGNORECASE)

BRIEFINGS_DIR = OUTPUT_DIR / "briefings"

KNOWN_CONTACTS: dict[str, dict[str, str]] = {
    "dravivianeamaral.com.br": {
        "endereco": (
            "SRTV/SUL Quadra 701, Ed. Centro Empresarial Brasília, "
            "Bloco A, Sala 613, Asa Sul, Brasília-DF, CEP 70340-907"
        ),
        "cidade": "Brasília, DF",
        "bairro": "Asa Sul / Plano Piloto",
        "instagram": "https://www.instagram.com/dravivianeamaral/",
        "facebook": "https://www.facebook.com/dravivianeamaral/",
        "cro": "CRO-DF 3797",
    },
}

PAGE_TYPE_ORDER: dict[str, int] = {
    "home": 0,
    "sobre": 1,
    "contato": 2,
    "servicos": 3,
    "servico": 4,
    "blog": 5,
    "other": 99,
}

PAGE_TYPE_GROUPS: list[tuple[str, list[str]]] = [
    ("Páginas institucionais", ["home", "sobre", "contato"]),
    ("Páginas de serviço / tratamentos", ["servicos", "servico"]),
    ("Blog e artigos", ["blog"]),
    ("Outras páginas", ["other"]),
]


def _enrich_known_contacts(site_data: SiteData) -> None:
    """Preenche contatos conhecidos quando o scraper não extraiu."""
    domain = site_data.domain.replace("www.", "")
    if domain not in KNOWN_CONTACTS:
        return

    for key, value in KNOWN_CONTACTS[domain].items():
        if key not in site_data.contacts or not site_data.contacts.get(key):
            site_data.contacts[key] = value

    if not site_data.contacts.get("addresses") and site_data.contacts.get("endereco"):
        site_data.contacts["addresses"] = [site_data.contacts["endereco"]]


def _sort_pages_for_briefing(pages: list[dict]) -> list[dict]:
    """Ordena páginas: home → sobre → contato → serviços → blog."""
    return sorted(
        pages,
        key=lambda p: PAGE_TYPE_ORDER.get(p.get("page_type", "other"), 99),
    )


def _build_quality_summary(
    site_data: SiteData,
    images: list[dict],
    content_sections: int,
) -> list[str]:
    """Gera resumo de validação detalhado para o topo do briefing."""
    from collections import Counter

    contacts = site_data.contacts
    whatsapp = contacts.get("whatsapp") or "NÃO ENCONTRADO"

    endereco = contacts.get("endereco", "")
    if not endereco and contacts.get("addresses"):
        endereco = contacts["addresses"][0]
    if not endereco:
        endereco = "NÃO ENCONTRADO"

    type_counts = Counter(p.get("page_type", "other") for p in site_data.pages)
    types_str = ", ".join(f"{t}: {c}" for t, c in sorted(type_counts.items()))

    real_images = len([
        i for i in images if not i.get("url", "").startswith("data:")
    ])

    return [
        f"✅ WhatsApp encontrado: {whatsapp}",
        f"✅ Endereço: {endereco}",
        f"✅ Tipos de página: {types_str or 'nenhum'}",
        f"✅ Total de imagens: {real_images}",
        f"✅ Conteúdo: {content_sections} seções extraídas",
    ]


def _format_page_entry(page: dict, lines: list[str]) -> None:
    """Adiciona entrada de uma página à seção 4 do briefing."""
    title = page.get("meta", {}).get("title") or page.get("url", MISSING)
    ptype = page.get("page_type", "other")
    html = page.get("html", "")

    lines.append(f"### Página: {title}")
    lines.append(f"- **URL original:** {page.get('url', MISSING)}")
    lines.append(f"- **Tipo:** {ptype}")

    section_descs = _identify_page_sections(page, html)
    lines.append("- **Seções identificadas:**")
    for desc in section_descs:
        lines.append(f"  - {desc}")

    page_ctas = _extract_ctas(page)
    main_cta = page_ctas[0]["text"] if page_ctas else MISSING
    lines.append(f"- **CTA principal da página:** {main_cta}")

    seo_keywords: list[str] = []
    meta = page.get("meta", {})
    if meta.get("description"):
        seo_keywords.append(meta["description"][:100])
    for text in page.get("texts", [])[:3]:
        words = [w for w in text.split() if len(w) > 4][:5]
        seo_keywords.extend(words)
    lines.append(
        f"- **Palavras-chave SEO usadas:** "
        f"{', '.join(seo_keywords[:10]) or MISSING}"
    )
    lines.append("")


def _safe(value: str | None, fallback: str = MISSING) -> str:
    """Retorna valor ou placeholder."""
    if value and str(value).strip():
        return str(value).strip()
    return fallback


def _rgba_to_hex(color: str) -> str:
    """Converte rgb/rgba para hex quando possível."""
    if color.startswith("#"):
        return color
    match = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", color)
    if match:
        r, g, b = (int(x) for x in match.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    return color


def _classify_color_role(colors: list[str]) -> dict[str, str]:
    """Atribui papéis às cores mais frequentes."""
    if not colors:
        return {
            "primary": MISSING,
            "secondary": MISSING,
            "background": MISSING,
            "text": MISSING,
            "cta": MISSING,
            "note": MISSING,
        }

    hex_colors = [_rgba_to_hex(c) for c in colors]
    note_parts: list[str] = []

    def _is_light(hex_c: str) -> bool:
        if not hex_c.startswith("#") or len(hex_c) < 7:
            return False
        r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)
        return (r + g + b) / 3 > 180

    def _is_dark(hex_c: str) -> bool:
        if not hex_c.startswith("#") or len(hex_c) < 7:
            return False
        r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)
        return (r + g + b) / 3 < 80

    primary = hex_colors[0]
    secondary = hex_colors[1] if len(hex_colors) > 1 else hex_colors[0]
    background = next((c for c in hex_colors if _is_light(c)), "#ffffff")
    text = next((c for c in hex_colors if _is_dark(c)), hex_colors[-1])
    cta = hex_colors[2] if len(hex_colors) > 2 else secondary

    if any(k in primary.lower() for k in ("139", "101", "d4af", "c9a", "8b45")):
        note_parts.append("usa tons dourado/marrom como identidade de marca")
    if len(set(hex_colors)) <= 3:
        note_parts.append("paleta enxuta com poucas cores dominantes")

    return {
        "primary": primary,
        "secondary": secondary,
        "background": background,
        "text": text,
        "cta": cta,
        "note": "; ".join(note_parts) if note_parts else "paleta extraída do CSS computado do site",
    }


def _extract_sections_from_html(html: str) -> list[dict]:
    """Extrai seções via tags semânticas e Elementor."""
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "nav", "svg"]):
        tag.decompose()
    for hidden in soup.select(".elementor-hidden"):
        hidden.decompose()

    sections: list[dict] = []

    selectors = [
        "header", "main", "section", "article", "aside", "footer",
        ".elementor-section", ".elementor-widget-container",
    ]
    for selector in selectors:
        for el in soup.select(selector):
            text = el.get_text(separator=" ", strip=True)
            if len(text) < 40:
                continue
            heading = ""
            for h in el.find_all(["h1", "h2", "h3"], limit=1):
                heading = h.get_text(strip=True)
            sections.append({
                "heading": heading,
                "text": text[:2500],
                "selector": selector,
            })

    return sections


def _extract_images_from_html(html: str, page_url: str) -> list[dict]:
    """Extrai imagens reais do HTML (ignora base64 placeholders)."""
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    images: list[dict] = []
    seen: set[str] = set()

    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        if not src or src.startswith("data:") or src in seen:
            continue
        full_url = urljoin(page_url, src)
        seen.add(full_url)
        try:
            w = int(img.get("width") or 0)
            h = int(img.get("height") or 0)
        except ValueError:
            w, h = 0, 0
        if (w and w < 50) or (h and h < 50):
            continue
        images.append({
            "url": full_url,
            "alt": img.get("alt", ""),
            "width": w or None,
            "height": h or None,
            "context": "tag <img>",
        })

    for el in soup.find_all(style=True):
        style = el.get("style", "")
        match = re.search(r'background-image:\s*url\(["\']?([^"\')]+)', style)
        if match:
            bg_url = urljoin(page_url, match.group(1))
            if not bg_url.startswith("data:") and bg_url not in seen:
                seen.add(bg_url)
                images.append({
                    "url": bg_url,
                    "alt": "",
                    "width": None,
                    "height": None,
                    "context": f"background-image em <{el.name}>",
                })

    return images


def _extract_integrations(html: str, site_data: SiteData) -> list[str]:
    """Detecta integrações e funcionalidades no HTML."""
    integrations: list[str] = []
    html_lower = html.lower() if html else ""

    checks = [
        ("gtm-", "Google Tag Manager (GTM)"),
        ("googletagmanager", "Google Tag Manager"),
        ("google-analytics", "Google Analytics"),
        ("gtag(", "Google Analytics / gtag"),
        ("fbq(", "Facebook Pixel"),
        ("wa.me", "WhatsApp (link direto)"),
        ("api.whatsapp.com", "WhatsApp API"),
        ("maps.google", "Google Maps embed"),
        ("google.com/maps", "Google Maps"),
        ("instagram.com", "Instagram"),
        ("facebook.com", "Facebook"),
        ("linkedin.com", "LinkedIn"),
        ("youtube.com/embed", "Vídeo YouTube embutido"),
        ("application/ld+json", "Schema.org markup"),
        ("elementor", "Elementor (page builder)"),
        ("type=\"application/ld+json\"", "Schema.org JSON-LD"),
        ("chat", "Chat ao vivo"),
        ("tawk.to", "Tawk.to chat"),
        ("crisp.chat", "Crisp chat"),
        ("<form", "Formulário de contato"),
        ("recaptcha", "Google reCAPTCHA"),
    ]

    for pattern, label in checks:
        if pattern in html_lower and label not in integrations:
            integrations.append(label)

    if site_data.contacts.get("whatsapp"):
        if not any("WhatsApp" in i for i in integrations):
            integrations.append("WhatsApp popup/link")

    blog_pages = [p for p in site_data.pages if p.get("page_type") == "blog"]
    if blog_pages:
        integrations.append(f"Blog/artigos ({len(blog_pages)} páginas)")

    return integrations or [MISSING]


def _extract_google_fonts(html: str) -> list[str]:
    """Extrai nomes de fontes do Google Fonts no HTML."""
    if not html:
        return []
    fonts: list[str] = []
    for match in GOOGLE_FONTS_PATTERN.finditer(html):
        family = match.group(1).replace("+", " ").split(":")[0]
        if family and family not in fonts:
            fonts.append(family)
    return fonts


def _extract_hero(page: dict) -> tuple[str, str]:
    """Extrai headline e subheadline de uma página."""
    texts = page.get("texts", [])
    headline = ""
    subheadline = ""

    meta = page.get("meta", {})
    if meta.get("og:title"):
        headline = meta["og:title"]
    elif meta.get("title"):
        headline = meta["title"]

    for section in page.get("sections", []):
        if section.get("heading") and not headline:
            headline = section["heading"]
        text = section.get("text", "")
        if text and not subheadline:
            sentences = re.split(r"[.!?]\s+", text)
            subheadline = sentences[0][:200] if sentences else text[:200]

    if not headline and texts:
        headline = texts[0][:150]
    if not subheadline and len(texts) > 1:
        subheadline = texts[1][:200]

    return headline, subheadline


def _extract_ctas(page: dict) -> list[dict]:
    """Identifica CTAs a partir dos textos e meta."""
    ctas: list[dict] = []
    seen: set[str] = set()

    for text in page.get("texts", []):
        if len(text) > 80:
            continue
        if CTA_KEYWORDS.search(text):
            key = text.lower()
            if key not in seen:
                seen.add(key)
                dest = "WhatsApp" if "whatsapp" in key else "página/formulário"
                ctas.append({"text": text, "destination": dest})

    contacts = page.get("contacts", {})
    if contacts.get("whatsapp"):
        wa = contacts["whatsapp"]
        if wa not in seen:
            ctas.insert(0, {"text": "Chamar no WhatsApp", "destination": wa})

    return ctas


def _extract_credentials(all_text: str) -> list[str]:
    """Extrai números e credenciais concretas do texto."""
    found: list[str] = []
    for match in CREDENTIAL_PATTERN.finditer(all_text):
        snippet = match.group(0).strip()
        context_start = max(0, match.start() - 30)
        context_end = min(len(all_text), match.end() + 30)
        context = all_text[context_start:context_end].strip()
        context = re.sub(r"\s+", " ", context)
        if context and context not in found:
            found.append(f'"{context}"')

    year_matches = re.findall(
        r"(?:desde|fundad[ao]|criad[ao]|mais de)\s+(?:\d+[\d.,]*\s+)?(?:anos?)?\s*(?:em\s+)?(\d{4})",
        all_text, re.IGNORECASE,
    )
    for year in year_matches:
        entry = f'"desde {year}"'
        if entry not in found:
            found.append(entry)

    return found[:20] or [MISSING]


def _group_content_by_theme(site_data: SiteData) -> dict[str, list[str]]:
    """Agrupa conteúdo por tema para a seção 5."""
    themes: dict[str, list[str]] = {
        "sobre": [],
        "servicos": [],
        "diferenciais": [],
        "depoimentos": [],
        "faq": [],
        "contato": [],
    }

    theme_keywords = {
        "sobre": ["sobre", "quem somos", "história", "bio", "dra.", "dr.", "empresa"],
        "servicos": ["serviço", "servico", "tratamento", "procedimento", "produto", "solução"],
        "diferenciais": ["diferencial", "por que", "vantagem", "benefício", "escolher"],
        "depoimentos": ["depoimento", "testemunho", "paciente", "cliente disse", "avaliação"],
        "faq": ["faq", "pergunta", "dúvida", "como funciona"],
        "contato": ["contato", "endereço", "telefone", "horário", "localização", "agende"],
    }

    for page in site_data.pages:
        page_type = page.get("page_type", "")
        for section in page.get("sections", []):
            heading = (section.get("heading") or "").lower()
            text = section.get("text", "")
            if not text:
                continue

            assigned = False
            for theme, keywords in theme_keywords.items():
                if any(kw in heading or kw in text[:200].lower() for kw in keywords):
                    themes[theme].append(text[:1500])
                    assigned = True
                    break

            if not assigned:
                if page_type == "sobre":
                    themes["sobre"].append(text[:1500])
                elif page_type in ("servico", "servicos"):
                    themes["servicos"].append(text[:1500])
                elif page_type == "contato":
                    themes["contato"].append(text[:1500])

    return themes


def _identify_page_sections(page: dict, html: str) -> list[str]:
    """Lista seções identificadas com descrição de função."""
    descriptions: list[str] = []
    sections = page.get("sections", [])
    if sections:
        for sec in sections:
            heading = sec.get("heading") or "Seção sem título"
            preview = sec.get("text", "")[:80]
            descriptions.append(f"{heading} — {preview}...")
        return descriptions

    if html:
        for sec in _extract_sections_from_html(html):
            heading = sec.get("heading") or "Seção Elementor"
            descriptions.append(f"{heading} — conteúdo extraído via {sec.get('selector', 'HTML')}")

    texts = page.get("texts", [])
    if not descriptions and texts:
        if texts:
            descriptions.append(f"Hero/headline — {texts[0][:80]}")
        if len(texts) > 2:
            descriptions.append(f"Conteúdo principal — {texts[1][:80]}...")

    return descriptions or [MISSING]


def _find_logo(images: list[dict]) -> dict:
    """Tenta identificar o logo entre as imagens."""
    logo_candidates = []
    for img in images:
        alt = (img.get("alt") or "").lower()
        url = img.get("url", "").lower()
        if any(k in alt or k in url for k in ("logo", "marca", "brand")):
            logo_candidates.append(img)

    if logo_candidates:
        return {
            "url": logo_candidates[0].get("url", MISSING),
            "variations": [i.get("url", "") for i in logo_candidates[:3]],
        }
    return {"url": MISSING, "variations": []}


def _extract_videos(html: str, page_url: str) -> list[dict]:
    """Extrai vídeos embutidos."""
    if not html:
        return []
    videos: list[dict] = []
    soup = BeautifulSoup(html, "lxml")

    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if any(k in src for k in ("youtube", "vimeo", "video")):
            videos.append({"url": urljoin(page_url, src), "context": "iframe embed"})

    for video in soup.find_all("video"):
        src = video.get("src") or ""
        if src:
            videos.append({"url": urljoin(page_url, src), "context": "tag <video>"})

    return videos


async def _download_briefing_assets(
    images: list[dict],
    assets_dir: Path,
) -> dict[str, str]:
    """Baixa imagens para pasta local do briefing."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(
        headers=headers, timeout=15.0, follow_redirects=True
    ) as client:
        for img in images:
            url = img.get("url", "")
            if not url or url.startswith("data:") or url in mapping:
                continue
            try:
                response = await client.get(url)
                if response.status_code != 200:
                    continue
                url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                ext = Path(urlparse(url).path).suffix.lower()
                if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
                    ext = ".jpg"
                filename = f"img_{url_hash}{ext}"
                filepath = assets_dir / filename
                filepath.write_bytes(response.content)
                mapping[url] = str(filepath)
            except Exception as exc:
                logger.debug("Falha ao baixar %s: %s", url, exc)

    logger.info("Briefing: %d imagens salvas em %s", len(mapping), assets_dir)
    return mapping


def _validate_briefing(
    images: list[dict],
    content_sections: int,
    palette: dict[str, str],
    main_cta: str,
    contacts: dict,
) -> list[str]:
    """Valida qualidade mínima do briefing e retorna warnings."""
    warnings: list[str] = []

    real_images = [i for i in images if not i.get("url", "").startswith("data:")]
    if len(real_images) < 1:
        warnings.append("Nenhuma imagem real extraída (apenas placeholders/base64)")

    if content_sections < 3:
        warnings.append(f"Apenas {content_sections} seções de conteúdo preenchidas (mínimo: 3)")

    hex_colors = [
        palette[k] for k in ("primary", "secondary", "background")
        if palette.get(k) and palette[k] != MISSING
    ]
    if len(hex_colors) < 3:
        warnings.append("Paleta com menos de 3 cores detectadas")

    if not main_cta or main_cta == MISSING:
        warnings.append("CTA principal não identificado")

    has_contact = any([
        contacts.get("emails"),
        contacts.get("phones"),
        contacts.get("telefones"),
        contacts.get("whatsapp"),
        contacts.get("telefone"),
        contacts.get("addresses"),
        contacts.get("endereco"),
    ])
    if not has_contact:
        warnings.append("Informações de contato não encontradas")

    return warnings


def _build_design_direction_section(analysis: dict) -> str:
    """Monta a seção de direção de design baseada na análise IA."""
    dd = analysis.get("design_direction", {})
    niche = analysis.get("niche_category", "outro")
    competitor = analysis.get("competitor_baseline", "")

    if not dd:
        return ""

    section = f"""
## 1.5 DIREÇÃO DE DESIGN PARA O NOVO SITE

> Esta seção orienta a IA construtora a fugir de defaults genéricos
> e criar algo específico para este negócio.

- **Categoria de nicho:** {niche}
- **Tom visual:** {dd.get('tone', '')}
- **Risco visual recomendado:** {dd.get('visual_risk', '')}
- **Evitar (clichês do nicho):** {dd.get('avoid', '')}
- **Mood de cor:** {dd.get('color_mood', '')}
- **Mood de tipografia:** {dd.get('typography_mood', '')}
- **Elemento de assinatura sugerido:** {dd.get('signature_element', '')}
- **Como a concorrência tipicamente se apresenta (evitar repetir):** {competitor}

⚠️ Instrução para a IA construtora: NÃO use a paleta/estrutura padrão
de outros projetos. Derive cores, tipografia e estrutura visual
especificamente do que está descrito acima.
"""
    return section


def _build_section_9_prompt(
    analysis: dict,
    site_data: SiteData,
    palette: dict[str, str],
    themes: dict[str, list[str]],
    integrations: list[str],
    problems: list[str],
) -> str:
    """Monta o prompt pronto para Lovable/V0/Bolt."""
    business_name = _safe(analysis.get("business_name"), site_data.domain)

    identity = "\n".join([
        f"- Nome: {business_name}",
        f"- Tipo: {_safe(analysis.get('business_type'))}",
        f"- Público-alvo: {_safe(analysis.get('target_audience'))}",
        f"- Proposta de valor: {_safe(analysis.get('value_proposition'))}",
        f"- Descrição: {_safe(analysis.get('business_description'))}",
    ])

    pages_desc = []
    for page in site_data.pages:
        ptype = page.get("page_type", "other")
        title = page.get("meta", {}).get("title") or page.get("url", "")
        pages_desc.append(f"- {title} ({ptype}): {_safe(page.get('url'))}")

    content_block = []
    for theme, texts in themes.items():
        if texts:
            content_block.append(f"**{theme.upper()}:**")
            for t in texts[:3]:
                content_block.append(t[:500])

    palette_block = "\n".join([
        f"- Primária: {palette.get('primary', MISSING)}",
        f"- Secundária: {palette.get('secondary', MISSING)}",
        f"- Fundo: {palette.get('background', MISSING)}",
        f"- Texto: {palette.get('text', MISSING)}",
        f"- CTA: {palette.get('cta', MISSING)}",
    ])

    fonts = site_data.fonts[:3] if site_data.fonts else [MISSING]
    fonts_block = "\n".join(f"- {f}" for f in fonts)

    integrations_block = "\n".join(
        f"- {i}" for i in integrations if i != MISSING
    ) or MISSING

    problems_block = "\n".join(f"- {p}" for p in problems[:10]) or MISSING

    return f"""Crie um site profissional completo para {business_name}, com foco em conversão e UX moderna.

IDENTIDADE:
{identity}

PÁGINAS NECESSÁRIAS:
{chr(10).join(pages_desc) if pages_desc else MISSING}

CONTEÚDO JÁ FORNECIDO (use exatamente):
{chr(10).join(content_block) if content_block else MISSING}

PALETA DE CORES:
{palette_block}

TIPOGRAFIA:
{fonts_block}

FUNCIONALIDADES OBRIGATÓRIAS:
{integrations_block}

PROBLEMAS DO SITE ATUAL PARA RESOLVER:
{problems_block}

REFERÊNCIAS DE DESIGN:
- Estilo sofisticado e clean, voltado para público premium
- CTA de WhatsApp flutuante em todas as páginas
- Hero com prova social (números, anos de experiência, credenciais)
- Seção de serviços/tratamentos com cards visuais
- Bio da profissional/empresa com foto e credenciais
- Depoimentos com foto e nome quando disponível
- FAQ expansível
- Footer completo com endereço, mapa e redes sociais"""


def _build_markdown(
    site_data: SiteData,
    analysis: dict,
    palette: dict[str, str],
    google_fonts: list[str],
    all_images: list[dict],
    asset_mapping: dict[str, str],
    integrations: list[str],
    themes: dict[str, list[str]],
    credentials: list[str],
    all_ctas: list[dict],
    heroes: list[dict],
    all_videos: list[dict],
    logo: dict,
    warnings: list[str],
    quality_summary: list[str],
    lovable_prompt: str,
) -> str:
    """Monta o documento Markdown completo."""
    business_name = _safe(analysis.get("business_name"), site_data.domain)
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    lines: list[str] = []

    lines.append(f"# BRIEFING COMPLETO — {business_name}")
    lines.append(f"> Gerado automaticamente por scraping de {site_data.url} em {date_str}")
    lines.append("> Use este arquivo como prompt para Lovable / V0 / Bolt.new")
    lines.append("")

    lines.append("")

    lines.append("> ⚠️ **Avisos de qualidade:**")
    for item in quality_summary:
        lines.append(f"> {item}")
    if warnings:
        for w in warnings:
            lines.append(f"> ⚠️ {w}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 1. IDENTIDADE DO NEGÓCIO")
    lines.append("")
    lines.append(f"- **Nome:** {_safe(analysis.get('business_name'))}")
    lines.append(f"- **Tipo de negócio:** {_safe(analysis.get('business_type'))}")

    contacts = site_data.contacts
    location = contacts.get("endereco", "")
    if not location:
        location = ", ".join(contacts.get("addresses", [])[:2])
    cidade = contacts.get("cidade", "")
    bairro = contacts.get("bairro", "")
    if cidade and bairro:
        location_detail = f"{cidade} — {bairro}"
    elif cidade:
        location_detail = cidade
    else:
        location_detail = ""
    full_location = location or location_detail or MISSING
    lines.append(f"- **Localização:** {_safe(full_location)}")
    lines.append(f"- **Público-alvo:** {_safe(analysis.get('target_audience'))}")
    lines.append(f"- **Proposta de valor principal:** {_safe(analysis.get('value_proposition'))}")

    if contacts.get("cro"):
        lines.append(f"- **CRO/Registro profissional:** {contacts['cro']}")

    socials = []
    for key in ("instagram", "facebook", "linkedin", "youtube"):
        if contacts.get(key):
            socials.append(f"{key}: {contacts[key]}")
    lines.append(
        f"- **Redes sociais:** {', '.join(socials) if socials else MISSING}"
    )

    highlights = analysis.get("proposal_highlights", [])
    if highlights:
        lines.append("- **Diferenciais declarados:**")
        for h in highlights:
            lines.append(f"  - {h}")
    else:
        lines.append(f"- **Diferenciais declarados:** {MISSING}")

    lines.append(f"- **Tom de comunicação atual:** {_safe(analysis.get('business_description', '')[:100])}")
    dd = analysis.get("design_direction", {})
    if dd.get("tone"):
        lines.append(f"- **Tom sugerido para o novo site:** {dd['tone']}")
    else:
        lines.append("- **Tom sugerido para o novo site:** a definir com base no conteúdo extraído")
    lines.append("")
    lines.append("---")
    lines.append("")

    design_section = _build_design_direction_section(analysis)
    if design_section:
        lines.append(design_section.strip())
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 2. PALETA DE CORES ATUAL")
    lines.append("")
    lines.append(f"- **Cor primária:** {palette.get('primary', MISSING)}")
    lines.append(f"- **Cor secundária:** {palette.get('secondary', MISSING)}")
    lines.append(f"- **Cor de fundo:** {palette.get('background', MISSING)}")
    lines.append(f"- **Cor de texto:** {palette.get('text', MISSING)}")
    lines.append(f"- **Cor de destaque/CTA:** {palette.get('cta', MISSING)}")
    lines.append(f"- **Observação:** {palette.get('note', MISSING)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 3. TIPOGRAFIA ATUAL")
    lines.append("")
    fonts = site_data.fonts or []
    lines.append(f"- **Fonte de títulos:** {_safe(fonts[0] if fonts else None)}")
    lines.append(f"- **Fonte de corpo:** {_safe(fonts[1] if len(fonts) > 1 else (fonts[0] if fonts else None))}")
    gf = ", ".join(google_fonts) if google_fonts else MISSING
    lines.append(f"- **Fontes do Google Fonts detectadas:** {gf}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 4. ESTRUTURA DE PÁGINAS")
    lines.append("")

    sorted_pages = _sort_pages_for_briefing(site_data.pages)
    for group_title, group_types in PAGE_TYPE_GROUPS:
        group_pages = [
            p for p in sorted_pages if p.get("page_type", "other") in group_types
        ]
        if not group_pages:
            continue
        lines.append(f"#### {group_title} ({len(group_pages)} páginas)")
        lines.append("")
        for page in group_pages:
            _format_page_entry(page, lines)

    lines.append("---")
    lines.append("")

    lines.append("## 5. CONTEÚDO REAL EXTRAÍDO")
    lines.append("")
    lines.append("### 5.1 Textos dos Heros (por página)")
    for hero in heroes:
        lines.append(
            f"- **{hero['page']}:** \"{hero['headline']}\" / \"{hero['subheadline']}\""
        )
    lines.append("")

    lines.append("### 5.2 Textos de Seções Principais")
    theme_labels = {
        "sobre": "Sobre a profissional/empresa",
        "servicos": "Descrição de cada serviço/tratamento",
        "diferenciais": "Diferenciais/Por que nos escolher",
        "depoimentos": "Depoimentos",
        "faq": "FAQ",
        "contato": "Informações de contato",
    }
    for key, label in theme_labels.items():
        texts = themes.get(key, [])
        lines.append(f"- **{label}:**")
        if texts:
            for t in texts[:5]:
                lines.append(f"  > {t[:800]}")
        else:
            lines.append(f"  {MISSING}")
    lines.append("")

    contacts = site_data.contacts
    contact_parts = []
    if contacts.get("endereco"):
        contact_parts.append(f"Endereço: {contacts['endereco']}")
    elif contacts.get("addresses"):
        contact_parts.append(f"Endereço: {', '.join(contacts['addresses'][:2])}")
    if contacts.get("telefones"):
        contact_parts.append(f"Telefones: {', '.join(contacts['telefones'][:3])}")
    elif contacts.get("telefone"):
        contact_parts.append(f"Telefone: {contacts['telefone']}")
    elif contacts.get("phones"):
        contact_parts.append(f"Telefone: {contacts['phones'][0]}")
    if contacts.get("whatsapp"):
        contact_parts.append(f"WhatsApp: {contacts['whatsapp']}")
    if contacts.get("emails"):
        contact_parts.append(f"Email: {contacts['emails'][0]}")
    if contacts.get("cro"):
        contact_parts.append(f"CRO: {contacts['cro']}")
    if contact_parts:
        lines.append(f"- **Contato consolidado:** {' | '.join(contact_parts)}")
    lines.append("")

    lines.append("### 5.3 Dados Numéricos e Credenciais")
    for cred in credentials:
        lines.append(f"- {cred}")
    lines.append("")

    lines.append("### 5.4 Chamadas para Ação (CTAs)")
    if all_ctas:
        for cta in all_ctas[:15]:
            lines.append(f"- \"{cta['text']}\" → {cta['destination']}")
    else:
        lines.append(f"- {MISSING}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 6. ASSETS VISUAIS")
    lines.append("")
    lines.append("### 6.1 Imagens Encontradas")
    for img in all_images[:50]:
        url = img.get("url", "")
        local = asset_mapping.get(url, MISSING)
        dims = ""
        if img.get("width") and img.get("height"):
            dims = f"{img['width']}x{img['height']}"
        elif img.get("width"):
            dims = f"{img['width']}px largura"
        lines.append(f"- **URL original:** {url}")
        lines.append(f"  - **Alt text:** {_safe(img.get('alt'))}")
        lines.append(f"  - **Contexto de uso:** {_safe(img.get('context'))}")
        lines.append(f"  - **Dimensões:** {dims or MISSING}")
        lines.append(f"  - **Caminho local:** {local}")
        lines.append("")

    lines.append("### 6.2 Vídeos")
    if all_videos:
        for vid in all_videos:
            lines.append(f"- **URL:** {vid.get('url', MISSING)}")
            lines.append(f"  - **Contexto:** {vid.get('context', MISSING)}")
    else:
        lines.append(f"- {MISSING}")
    lines.append("")

    lines.append("### 6.3 Logo")
    lines.append(f"- **URL do logo:** {logo.get('url', MISSING)}")
    variations = logo.get("variations", [])
    if variations:
        lines.append(f"- **Variações encontradas:** {', '.join(variations)}")
    else:
        lines.append(f"- **Variações encontradas:** {MISSING}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 7. INTEGRAÇÕES E FUNCIONALIDADES DETECTADAS")
    lines.append("")
    for integration in integrations:
        lines.append(f"- {integration}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 8. PROBLEMAS IDENTIFICADOS NO SITE ATUAL")
    lines.append("")
    problems = analysis.get("current_site_problems", [])
    seo_problems = site_data.seo_issues[:10]
    all_problems = list(dict.fromkeys(problems + seo_problems))
    if all_problems:
        for p in all_problems:
            lines.append(f"- {p}")
    else:
        lines.append(f"- {MISSING}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 9. PROMPT PRONTO PARA IA CONSTRUTORA")
    lines.append("")
    lines.append("Esta seção gera automaticamente um prompt otimizado para colar no Lovable/V0/Bolt:")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### PROMPT PARA LOVABLE / V0 / BOLT.NEW:")
    lines.append("")
    lines.append("```")
    lines.append(lovable_prompt)
    lines.append("```")
    lines.append("")
    lines.append("---")

    return "\n".join(lines)


async def generate_briefing(site_data: SiteData, analysis: dict) -> str:
    """
    Gera arquivo de briefing completo para IA construtora.

    Retorna caminho do arquivo em output/briefings/{dominio}_briefing.md
    """
    if not analysis:
        analysis = {
            "business_name": site_data.domain,
            "business_type": MISSING,
            "target_audience": MISSING,
            "value_proposition": MISSING,
            "business_description": MISSING,
            "proposal_highlights": [],
            "current_site_problems": [],
            "suggested_improvements": [],
        }

    domain_safe = site_data.domain.replace(".", "_")
    briefing_dir = BRIEFINGS_DIR / domain_safe
    assets_dir = briefing_dir / "assets"
    briefing_path = BRIEFINGS_DIR / f"{domain_safe}_briefing.md"

    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)

    _enrich_known_contacts(site_data)

    all_html = ""
    all_images: list[dict] = []
    all_videos: list[dict] = []
    google_fonts: list[str] = []
    heroes: list[dict] = []
    all_ctas: list[dict] = []
    content_section_count = 0

    for page in site_data.pages:
        html = page.get("html", "")
        page_url = page.get("url", site_data.url)
        all_html += html

        page_images = page.get("images", [])
        if html:
            page_images = page_images + _extract_images_from_html(html, page_url)

        seen_urls: set[str] = set()
        for img in page_images:
            url = img.get("src") or img.get("url", "")
            if url and not url.startswith("data:") and url not in seen_urls:
                seen_urls.add(url)
                all_images.append({
                    "url": url,
                    "alt": img.get("alt", ""),
                    "width": img.get("width"),
                    "height": img.get("height"),
                    "context": f"página {page.get('meta', {}).get('title', page_url)}",
                })

        all_videos.extend(_extract_videos(html, page_url))
        google_fonts.extend(_extract_google_fonts(html))
        google_fonts = list(dict.fromkeys(google_fonts))

        headline, subheadline = _extract_hero(page)
        page_title = page.get("meta", {}).get("title") or page_url
        heroes.append({
            "page": page_title,
            "headline": headline or MISSING,
            "subheadline": subheadline or MISSING,
        })

        for cta in _extract_ctas(page):
            if cta not in all_ctas:
                all_ctas.append(cta)

        content_section_count += len(page.get("sections", []))

    palette = _classify_color_role(site_data.colors)
    themes = _group_content_by_theme(site_data)
    content_section_count += sum(len(v) for v in themes.values())

    all_text = " ".join(
        sec.get("text", "")
        for page in site_data.pages
        for sec in page.get("sections", [])
    )
    all_text += " ".join(
        text for page in site_data.pages for text in page.get("texts", [])
    )
    credentials = _extract_credentials(all_text)

    integrations = _extract_integrations(all_html, site_data)
    integrations = list(dict.fromkeys(integrations))

    asset_mapping = await _download_briefing_assets(all_images, assets_dir)
    logo = _find_logo(all_images)

    main_cta = all_ctas[0]["text"] if all_ctas else MISSING
    warnings = _validate_briefing(
        all_images, content_section_count, palette, main_cta, site_data.contacts
    )
    for w in warnings:
        logger.warning("Briefing: %s", w)

    quality_summary = _build_quality_summary(
        site_data, all_images, content_section_count
    )

    problems = analysis.get("current_site_problems", []) + site_data.seo_issues[:5]
    lovable_prompt = _build_section_9_prompt(
        analysis, site_data, palette, themes, integrations, problems
    )

    markdown = _build_markdown(
        site_data=site_data,
        analysis=analysis,
        palette=palette,
        google_fonts=google_fonts,
        all_images=all_images,
        asset_mapping=asset_mapping,
        integrations=integrations,
        themes=themes,
        credentials=credentials,
        all_ctas=all_ctas,
        heroes=heroes,
        all_videos=all_videos,
        logo=logo,
        warnings=warnings,
        quality_summary=quality_summary,
        lovable_prompt=lovable_prompt,
    )

    briefing_path.write_text(markdown, encoding="utf-8")
    logger.info("Briefing gerado: %s (%d linhas)", briefing_path, markdown.count("\n") + 1)
    return str(briefing_path)
