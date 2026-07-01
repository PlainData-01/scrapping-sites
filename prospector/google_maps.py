"""
Busca negócios no Google Maps e retorna lista de leads com site.
Suporta dois modos:
- Com GOOGLE_MAPS_API_KEY no .env: usa Google Places API (mais confiável)
- Sem key: usa scraping via Playwright no Google Maps (gratuito, mais lento)
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

NOMES_INVALIDOS = frozenset({"Resultados", "Maps", "Google Maps", ""})

DOMINIOS_INVALIDOS = [
    "instagram.com", "facebook.com", "linktr.ee", "linktree.com",
    "sites.google.com", "wa.me", "whatsapp.com", "wix.com/website",
    "tiktok.com", "twitter.com", "x.com", "youtube.com",
    "beacons.ai", "linkin.bio", "carrd.co", "bio.link",
]

DOMINIOS_TERCEIRIZADOS = [
    "meudoutor.com",
]


@dataclass
class Lead:
    nome: str
    endereco: str
    telefone: str
    website: str
    google_maps_url: str
    avaliacao: float = 0.0
    total_avaliacoes: int = 0
    categoria: str = ""
    status: str = "pendente"  # pendente | processado | sem_site | ignorado | erro

    # Qualificação
    score: int = 0
    score_detalhes: dict = field(default_factory=dict)
    plataforma_detectada: str = ""
    qualificado: bool = True
    motivo_descarte: str = ""
    prioridade: str = "media"  # alta | media | baixa
    site_terceirizado: bool = False


def _limpar_telefone(tel: str) -> str:
    """Limpa e valida número de telefone brasileiro."""
    if not tel:
        return ""
    digits = re.sub(r"\D", "", tel)
    if digits.startswith("5555"):
        digits = digits[2:]
    if digits.startswith("55") and len(digits) > 13:
        return ""
    if not digits.startswith("55"):
        if digits.startswith("61") or digits.startswith("0"):
            digits = "55" + digits.lstrip("0")
        elif len(digits) in (10, 11):
            digits = "55" + digits
    if not (12 <= len(digits) <= 13):
        return ""
    return digits


def _telefone_compativel_whatsapp(tel: str) -> bool:
    """Celular BR válido para WhatsApp (DDD + 9 dígitos)."""
    digits = _limpar_telefone(tel)
    if not digits:
        return False
    if len(digits) == 13 and digits.startswith("55"):
        return digits[4] == "9"
    if len(digits) == 11:
        return digits[2] == "9"
    return False


def _telefone_valido(tel: str) -> bool:
    """Telefone brasileiro com formato mínimo válido."""
    digits = _limpar_telefone(tel)
    return len(digits) in (12, 13)


def _lead_prioridade_ordenacao(lead: Lead) -> tuple[int, int]:
    """Ordenação: WhatsApp compatível primeiro, depois score."""
    if _telefone_compativel_whatsapp(lead.telefone):
        tel_rank = 0
    elif _telefone_valido(lead.telefone):
        tel_rank = 1
    else:
        tel_rank = 2
    return (tel_rank, -lead.score)


def _nome_valido(nome: str) -> bool:
    if not nome or nome in NOMES_INVALIDOS:
        return False
    return not nome[0].isdigit()


def _eh_site_proprio(website: str) -> bool:
    """Verifica se o link é um site próprio, não rede social ou agregador."""
    if not website:
        return False
    website_lower = website.lower()
    for dominio in DOMINIOS_INVALIDOS:
        if dominio in website_lower:
            return False
    return True


def _eh_site_terceirizado(website: str) -> bool:
    """Perfil em plataforma de terceiros (ex.: meudoutor.com) — válido mas flag especial."""
    if not website:
        return False
    website_lower = website.lower()
    return any(d in website_lower for d in DOMINIOS_TERCEIRIZADOS)


def _avaliar_website_maps(website: str) -> tuple[bool, bool, str]:
    """
    Avalia URL extraída do Maps.
    Retorna (aceitar, site_terceirizado, motivo_descarte).
    """
    if not _eh_site_proprio(website):
        for dominio in DOMINIOS_INVALIDOS:
            if dominio in website.lower():
                return False, False, f"Link inválido (não é site próprio): {dominio}"
        return False, False, "Link inválido (não é site próprio)"
    return True, _eh_site_terceirizado(website), ""


async def _extrair_nome(page) -> str:
    """Extrai nome do negócio do painel lateral do Maps."""
    seletores = [
        "h1.DUwDvf",
        'h1[class*="fontHeadlineLarge"]',
        '[data-attrid="title"] span',
        "h1",
    ]
    for seletor in seletores:
        try:
            el = await page.query_selector(seletor)
            if el:
                texto = (await el.inner_text()).strip()
                if _nome_valido(texto):
                    return texto
        except Exception:
            continue
    return ""


async def detectar_plataforma(website: str) -> str:
    """Detecta plataforma com mais padrões e fallbacks."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                website,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36"
                    ),
                },
            )
            html = resp.text[:8000]
            final_url = str(resp.url)

        checks = {
            "wix": [
                "wixstatic.com" in html,
                "wix.com" in html,
                "_wixCIDX" in html,
                "X-Wix" in str(resp.headers),
                "wixsite.com" in final_url,
                "parastorage.com" in html,
            ],
            "wordpress": [
                "/wp-content/" in html,
                "/wp-includes/" in html,
                'content="WordPress' in html,
                "wp-json" in html,
                "/wp-admin" in html,
            ],
            "squarespace": [
                "squarespace.com" in html,
                "static.squarespace.com" in html,
                "squarespace-cdn.com" in html,
            ],
            "webflow": [
                "webflow.com" in html,
                "assets-global.website-files.com" in html,
                "webflow.io" in final_url,
            ],
            "shopify": [
                "cdn.shopify.com" in html,
                "myshopify.com" in html,
            ],
            "hostinger": [
                "hostingersite.com" in html,
                "hostinger.com" in final_url,
            ],
            "duda": [
                "multiscreensite.com" in html,
                "lirp.cdn-website.com" in html,
                "dd-cdn.multiscreensite.com" in html,
            ],
            "elementor": [
                "elementor" in html.lower() and "/wp-content/" in html,
            ],
        }

        for plataforma, sinais in checks.items():
            if any(sinais):
                return plataforma

        return "custom"
    except Exception as exc:
        logger.debug("Erro ao detectar plataforma de %s: %s", website, exc)
        return "desconhecida"


async def qualificar_lead(lead: Lead) -> Lead:
    """Avalia lead e atribui score, prioridade e motivo de descarte."""
    score = 0
    detalhes: dict = {}

    REDES_EXCLUIR = [
        "orthopride", "odonto company", "odontocompany", "sorridents",
        "odontoprev", "uniodonto", "dr. consulta", "drconsulta",
        "hospital", "ubs", "posto de saúde", "oral sin", "dental uno",
    ]
    nome_lower = lead.nome.lower()
    for rede in REDES_EXCLUIR:
        if rede in nome_lower:
            lead.qualificado = False
            lead.motivo_descarte = f"Rede/franquia: '{rede}'"
            return lead

    if lead.website and lead.website.startswith("http://"):
        lead.qualificado = False
        lead.motivo_descarte = "Site sem HTTPS"
        return lead

    if lead.total_avaliacoes > 10 and lead.avaliacao < 3.2:
        lead.qualificado = False
        lead.motivo_descarte = f"Avaliação muito baixa ({lead.avaliacao}★)"
        return lead

    plataforma = await detectar_plataforma(lead.website)
    lead.plataforma_detectada = plataforma
    plataforma_scores = {
        "wix": (35, "Wix detectado — argumento de venda direto"),
        "squarespace": (30, "Squarespace — limitações de SEO"),
        "duda": (28, "Duda/Multiscreen — builder limitado, argumento fácil"),
        "hostinger": (25, "Hostinger builder — qualidade geralmente baixa"),
        "wordpress": (15, "WordPress — verificar se está desatualizado"),
        "elementor": (12, "WordPress + Elementor — verificar performance"),
        "webflow": (5, "Webflow — provavelmente bem feito"),
        "shopify": (5, "Shopify — e-commerce, fora do escopo padrão"),
        "custom": (10, "Site custom — verificar qualidade"),
        "desconhecida": (8, "Plataforma não identificada"),
    }
    pts, motivo = plataforma_scores.get(plataforma, (5, ""))
    score += pts
    detalhes["plataforma"] = {"pontos": pts, "motivo": motivo}

    if 3.8 <= lead.avaliacao <= 4.6:
        pts, motivo = 20, f"Avaliação ideal ({lead.avaliacao}★)"
    elif lead.avaliacao > 4.6:
        pts, motivo = 10, f"Avaliação muito alta ({lead.avaliacao}★)"
    elif 3.2 <= lead.avaliacao < 3.8:
        pts, motivo = 8, f"Avaliação razoável ({lead.avaliacao}★)"
    else:
        pts, motivo = 0, f"Avaliação baixa ({lead.avaliacao}★)"
    score += pts
    detalhes["avaliacao"] = {"pontos": pts, "motivo": motivo}

    if lead.total_avaliacoes >= 100:
        pts, motivo = 20, f"{lead.total_avaliacoes} avaliações — muito ativo"
    elif lead.total_avaliacoes >= 50:
        pts, motivo = 15, f"{lead.total_avaliacoes} avaliações — ativo"
    elif lead.total_avaliacoes >= 20:
        pts, motivo = 10, f"{lead.total_avaliacoes} avaliações"
    elif lead.total_avaliacoes >= 10:
        pts, motivo = 5, f"{lead.total_avaliacoes} avaliações"
    else:
        pts, motivo = 0, f"Poucas avaliações ({lead.total_avaliacoes})"
    score += pts
    detalhes["volume"] = {"pontos": pts, "motivo": motivo}

    if lead.total_avaliacoes >= 200:
        score += 10
        detalhes["ativo"] = {
            "pontos": 10,
            "motivo": "Negócio muito ativo (+200 avaliações)",
        }

    tel_limpo = _limpar_telefone(lead.telefone)
    if _telefone_compativel_whatsapp(lead.telefone):
        score += 25
        detalhes["whatsapp"] = {
            "pontos": 25,
            "motivo": "WhatsApp compatível (celular BR)",
        }
    elif _telefone_valido(lead.telefone):
        score += 8
        detalhes["whatsapp"] = {
            "pontos": 8,
            "motivo": "Telefone fixo válido",
        }
    elif tel_limpo:
        detalhes["whatsapp"] = {
            "pontos": 0,
            "motivo": "Telefone com formato incomum",
        }
    else:
        detalhes["whatsapp"] = {
            "pontos": -5,
            "motivo": "Sem telefone no Maps",
        }
        score = max(0, score - 5)

    REGIOES_PREMIUM = [
        "asa sul", "asa norte", "lago sul", "lago norte",
        "sudoeste", "noroeste", "águas claras", "park sul",
    ]
    for regiao in REGIOES_PREMIUM:
        if regiao in lead.endereco.lower():
            score += 10
            detalhes["localizacao"] = {
                "pontos": 10,
                "motivo": f"Região premium: {regiao.title()}",
            }
            break

    lead.score = min(score, 100)
    lead.score_detalhes = detalhes
    lead.prioridade = "alta" if score >= 65 else "media" if score >= 35 else "baixa"

    return lead


def ajustar_score_pos_scraping(lead: Lead, seo_issues_count: int) -> Lead:
    """Ajusta score após scraping com base nos problemas SEO reais."""
    if lead.plataforma_detectada == "webflow" and seo_issues_count < 3:
        lead.score = max(0, lead.score - 15)
        lead.score_detalhes["site_bom"] = {
            "pontos": -15,
            "motivo": "Site provavelmente bem feito",
        }
        lead.prioridade = (
            "alta" if lead.score >= 65
            else "media" if lead.score >= 35
            else "baixa"
        )
    return lead


async def _site_acessivel(website: str) -> tuple[bool, str]:
    """Verifica rapidamente se o site está acessível."""
    import httpx
    from urllib.parse import urlparse

    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            try:
                resp = await client.head(website)
            except httpx.HTTPError:
                resp = await client.get(website)
            if resp.status_code >= 400:
                return False, f"HTTP {resp.status_code}"

            original = urlparse(website).netloc.replace("www.", "")
            final = urlparse(str(resp.url)).netloc.replace("www.", "")
            if original and final and original != final:
                return False, f"Redireciona para {final}"
            return True, ""
    except Exception as exc:
        return False, str(exc)[:50]


async def _contar_cards_maps(page) -> int:
    """Conta cards de resultado visíveis no painel lateral."""
    cards = await page.query_selector_all('[role="feed"] [role="article"]')
    if not cards:
        cards = await page.query_selector_all('[role="article"]')
    return len(cards)


async def _scroll_maps(page) -> None:
    """Rola o feed de resultados para carregar mais cards."""
    feed = await page.query_selector('[role="feed"]')
    if feed:
        await feed.evaluate("el => el.scrollTop = el.scrollHeight")
    await page.keyboard.press("End")
    await asyncio.sleep(1.5)


async def buscar_leads(
    query: str = "clínica odontológica",
    cidade: str = "Brasília DF",
    max_results: int = 50,
    apenas_qualificados: bool = True,
) -> list[Lead]:
    """
    Busca negócios no Google Maps, qualifica e ordena por score.
    Tenta Google Places API primeiro, depois fallback Playwright.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    meta_candidatos = _meta_candidatos(max_results)
    if api_key:
        leads_brutos = await _buscar_via_places_api(
            query, cidade, meta_candidatos, api_key,
        )
    else:
        logger.warning(
            "GOOGLE_MAPS_API_KEY não configurada. "
            "Usando scraping via Playwright (mais lento e menos confiável). "
            "Para resultados melhores, configure a key gratuita em "
            "console.cloud.google.com (200 USD/mês de crédito gratuito)."
        )
        leads_brutos = await _buscar_via_playwright(
            query, cidade, meta_candidatos, meta_qualificados=max_results,
        )

    aprovados = await _qualificar_e_filtrar(leads_brutos, apenas_qualificados)
    return aprovados[:max_results]


def _meta_candidatos(max_qualificados: int) -> int:
    """
    Quantos negócios com site buscar no Maps antes da qualificação.
    Muitos listings não têm site ou são filtrados — buffer alto evita retorno curto.
    """
    return max(max_qualificados * 5, max_qualificados + 20, 30)


async def buscar_leads_com_descartados(
    query: str = "clínica odontológica",
    cidade: str = "Brasília DF",
    max_results: int = 50,
) -> tuple[list[Lead], list[Lead]]:
    """Retorna (aprovados até max_results, descartados) após qualificação."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    meta_candidatos = _meta_candidatos(max_results)

    if api_key:
        leads_brutos = await _buscar_via_places_api(
            query, cidade, meta_candidatos, api_key,
        )
    else:
        logger.warning(
            "GOOGLE_MAPS_API_KEY não configurada. Usando scraping via Playwright."
        )
        leads_brutos = await _buscar_via_playwright(
            query, cidade, meta_candidatos, meta_qualificados=max_results,
        )

    aprovados = await _qualificar_e_filtrar(leads_brutos, apenas_qualificados=True)
    descartados = [l for l in leads_brutos if not l.qualificado]
    descartados.sort(key=lambda l: l.score, reverse=True)

    if len(aprovados) < max_results:
        logger.warning(
            "Solicitados %d leads qualificados, encontrados %d "
            "(%d candidatos com site, %d descartados na qualificação)",
            max_results, len(aprovados), len(leads_brutos), len(descartados),
        )

    return aprovados[:max_results], descartados


async def _qualificar_e_filtrar(
    leads_brutos: list[Lead],
    apenas_qualificados: bool,
) -> list[Lead]:
    """Qualifica leads em paralelo e retorna lista filtrada/ordenada."""
    sem = asyncio.Semaphore(5)

    async def qualificar_com_limite(lead: Lead) -> Lead:
        async with sem:
            return await qualificar_lead(lead)

    leads = await asyncio.gather(*[qualificar_com_limite(l) for l in leads_brutos])

    aprovados = [l for l in leads if l.qualificado]
    descartados = [l for l in leads if not l.qualificado]

    logger.info(
        "Qualificação: %d aprovados | %d descartados | Alta: %d | Média: %d | Baixa: %d",
        len(aprovados), len(descartados),
        sum(1 for l in aprovados if l.prioridade == "alta"),
        sum(1 for l in aprovados if l.prioridade == "media"),
        sum(1 for l in aprovados if l.prioridade == "baixa"),
    )

    resultado = aprovados if apenas_qualificados else list(leads)
    resultado.sort(key=_lead_prioridade_ordenacao)
    return resultado


async def _buscar_via_places_api(
    query: str, cidade: str, max_results: int, api_key: str
) -> list[Lead]:
    """Usa Google Places API (Text Search + Place Details)."""
    import httpx

    leads: list[Lead] = []
    next_page_token: str | None = None
    search_query = f"{query} em {cidade}"

    async with httpx.AsyncClient(timeout=30) as client:
        while len(leads) < max_results:
            params: dict[str, str] = {
                "query": search_query,
                "key": api_key,
                "language": "pt-BR",
            }
            if next_page_token:
                params["pagetoken"] = next_page_token
                await asyncio.sleep(2)

            resp = await client.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params=params,
            )
            data = resp.json()

            status = data.get("status")
            if status not in ("OK", "ZERO_RESULTS"):
                logger.error("Places API erro: %s — %s", status, data.get("error_message", ""))
                break

            for place in data.get("results", []):
                if len(leads) >= max_results:
                    break

                details_resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/details/json",
                    params={
                        "place_id": place["place_id"],
                        "fields": (
                            "name,formatted_address,formatted_phone_number,"
                            "website,url,rating,user_ratings_total,types"
                        ),
                        "key": api_key,
                        "language": "pt-BR",
                    },
                )
                det = details_resp.json().get("result", {})
                website = det.get("website", "")

                if not website:
                    logger.debug("Sem site: %s — ignorado", det.get("name", "?"))
                    continue

                aceitar, site_terceirizado, motivo = _avaliar_website_maps(website)
                if not aceitar:
                    logger.debug(
                        "Descartando link inválido (não é site próprio): %s — %s",
                        website, det.get("name", "?"),
                    )
                    continue

                telefone_raw = det.get("formatted_phone_number", "")
                telefone = _limpar_telefone(telefone_raw) or telefone_raw

                leads.append(Lead(
                    nome=det.get("name", ""),
                    endereco=det.get("formatted_address", ""),
                    telefone=telefone,
                    website=website,
                    google_maps_url=det.get("url", ""),
                    avaliacao=float(det.get("rating") or 0.0),
                    total_avaliacoes=int(det.get("user_ratings_total") or 0),
                    categoria=", ".join(det.get("types", [])[:2]),
                    site_terceirizado=site_terceirizado,
                ))

            next_page_token = data.get("next_page_token")
            if not next_page_token:
                break

    logger.info("Places API: %d leads com site encontrados", len(leads))
    return leads


async def _extrair_website_painel(page) -> str:
    """Extrai URL do site a partir do painel lateral do Maps."""
    seletores = (
        'a[data-item-id="authority"]',
        'a[aria-label*="Site"]',
        'a[aria-label*="site"]',
        'a[aria-label*="Website"]',
        'a[href^="http"]:has-text("Site")',
        'a[href^="http"]:has-text("site")',
        'button[data-item-id="authority"]',
    )
    for selector in seletores:
        try:
            el = await page.query_selector(selector)
            if not el:
                continue
            href = (await el.get_attribute("href")) or ""
            if href.startswith("http"):
                return href
            data = (await el.get_attribute("data-item-id")) or ""
            if data.startswith("http"):
                return data
        except Exception:
            continue
    return ""


async def _buscar_via_playwright(
    query: str,
    cidade: str,
    meta_candidatos: int,
    meta_qualificados: int | None = None,
) -> list[Lead]:
    """Fallback: scraping do Google Maps via Playwright."""
    from playwright.async_api import async_playwright

    from config import USER_AGENT

    leads: list[Lead] = []
    seen_websites: set[str] = set()
    search_url = (
        f"https://www.google.com/maps/search/"
        f"{query.replace(' ', '+')}+{cidade.replace(' ', '+')}"
    )

    # Muitos cards não têm site — percorrer bem mais cards que o alvo final.
    max_cards_visitar = max(meta_candidatos * 8, 80)
    max_scrolls_sem_novos = 8
    scrolls_sem_novos = 0
    card_index = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=USER_AGENT)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        while (
            len(leads) < meta_candidatos
            and card_index < max_cards_visitar
            and scrolls_sem_novos < max_scrolls_sem_novos
        ):
            total_cards = await _contar_cards_maps(page)

            while (
                card_index < total_cards
                and len(leads) < meta_candidatos
                and card_index < max_cards_visitar
            ):
                cards = await page.query_selector_all('[role="feed"] [role="article"]')
                if not cards:
                    cards = await page.query_selector_all('[role="article"]')
                if card_index >= len(cards):
                    break

                card = cards[card_index]
                card_index += 1
                try:
                    await card.click()
                    await asyncio.sleep(1.5)

                    nome = await _extrair_nome(page)
                    if not _nome_valido(nome):
                        logger.debug("Nome inválido '%s' — descartando card", nome)
                        continue

                    website = await _extrair_website_painel(page)
                    if not website or not nome:
                        continue

                    aceitar, site_terceirizado, _ = _avaliar_website_maps(website)
                    if not aceitar:
                        logger.debug(
                            "Descartando link inválido (não é site próprio): %s", website,
                        )
                        continue

                    if website in seen_websites:
                        continue
                    seen_websites.add(website)

                    telefone = ""
                    tel_el = await page.query_selector(
                        'button[data-item-id^="phone"], [data-tooltip*="telefone"]'
                    )
                    if tel_el:
                        telefone_raw = (await tel_el.inner_text()).strip()
                        telefone = _limpar_telefone(telefone_raw) or telefone_raw

                    endereco = ""
                    end_el = await page.query_selector('[data-item-id="address"]')
                    if end_el:
                        endereco = (await end_el.inner_text()).strip()

                    avaliacao = 0.0
                    total_avaliacoes = 0
                    rating_el = await page.query_selector(
                        'div.F7nice span[aria-hidden="true"], span.ceNzKf[aria-hidden="true"]'
                    )
                    if rating_el:
                        try:
                            avaliacao = float(
                                (await rating_el.inner_text()).replace(",", ".")
                            )
                        except ValueError:
                            pass
                    reviews_el = await page.query_selector(
                        'div.F7nice span[aria-label*="avalia"], '
                        'button[aria-label*="avalia"]'
                    )
                    if reviews_el:
                        label = (
                            (await reviews_el.get_attribute("aria-label")) or ""
                        ).lower()
                        match = re.search(r"([\d\.]+)\s*mil", label)
                        if match:
                            total_avaliacoes = int(float(match.group(1)) * 1000)
                        else:
                            match = re.search(r"(\d+)", label.replace(".", ""))
                            if match:
                                total_avaliacoes = int(match.group(1))

                    leads.append(Lead(
                        nome=nome,
                        endereco=endereco,
                        telefone=telefone,
                        website=website,
                        google_maps_url=page.url,
                        avaliacao=avaliacao,
                        total_avaliacoes=total_avaliacoes,
                        site_terceirizado=site_terceirizado,
                    ))
                except Exception as exc:
                    logger.debug("Erro ao extrair card: %s", exc)
                    continue

            if len(leads) >= meta_candidatos:
                break

            cards_antes = total_cards
            await _scroll_maps(page)
            cards_depois = await _contar_cards_maps(page)
            if cards_depois <= cards_antes:
                scrolls_sem_novos += 1
            else:
                scrolls_sem_novos = 0

        await browser.close()

    alvo = meta_qualificados or meta_candidatos
    logger.info(
        "Playwright: %d leads com site extraídos (%d cards visitados, alvo %d)",
        len(leads), card_index, alvo,
    )
    return leads


def salvar_csv(leads: list[Lead], path: str = "output/leads/leads.csv") -> str:
    """Salva os leads em CSV para acompanhamento."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "prioridade", "score", "nome", "plataforma_detectada",
        "avaliacao", "total_avaliacoes", "telefone", "website",
        "endereco", "google_maps_url", "qualificado",
        "motivo_descarte", "problema_principal",
        "mensagem_whatsapp", "whatsapp_link", "status",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            row = asdict(lead)
            writer.writerow(row)
    return str(out)


def lead_para_dict(lead: Lead) -> dict:
    """Serializa Lead para JSON/SSE."""
    d = asdict(lead)
    return d
