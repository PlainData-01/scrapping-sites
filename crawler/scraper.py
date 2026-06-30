"""Extração de conteúdo de páginas com Playwright."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import Browser, Page, async_playwright

from config import OUTPUT_DIR, USER_AGENT

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
PHONE_PATTERN = re.compile(
    r"(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}[-.\s]?\d{4}"
)
WA_ME_PATTERN = re.compile(r"wa\.me\/(\d{10,13})")
TELEFONE_PATTERN = re.compile(
    r"(?:\+55\s?)?(?:\(?\d{2}\)?\s?)(?:9\s?)?\d{4}[-\s]?\d{4}"
)

WHATSAPP_JS = """
() => {
    const results = {};

    const waLinks = document.querySelectorAll('a[href*="wa.me"]');
    waLinks.forEach(a => { results.whatsapp_url = a.href; });

    const apiLinks = document.querySelectorAll('a[href*="api.whatsapp.com"]');
    apiLinks.forEach(a => { results.whatsapp_api = a.href; });

    document.querySelectorAll(
        '[data-url*="whatsapp"], [data-href*="whatsapp"], [data-link*="whatsapp"]'
    ).forEach(el => {
        results.whatsapp_data = el.dataset.url || el.dataset.href || el.dataset.link;
    });

    const bodyText = document.body.innerText;
    const phoneRegex = /(?:\\+55\\s?)?(?:\\(?\\d{2}\\)?\\s?)(?:9\\s?)?\\d{4}[-\\s]?\\d{4}/g;
    const phones = bodyText.match(phoneRegex);
    if (phones) results.phones = [...new Set(phones)];

    document.querySelectorAll('[onclick*="whatsapp"], [onclick*="wa.me"]')
        .forEach(el => { results.whatsapp_onclick = el.getAttribute('onclick'); });

    return results;
}
"""

_browser: Browser | None = None
_playwright = None


async def _get_browser() -> Browser:
    """Retorna instância singleton do browser Chromium."""
    global _browser, _playwright
    if _browser is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
    return _browser


async def close_browser() -> None:
    """Fecha o browser e libera recursos do Playwright."""
    global _browser, _playwright
    if _browser:
        try:
            for context in list(_browser.contexts):
                await context.close()
        except Exception:
            pass
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
    # Permite ao event loop finalizar transports de subprocesso no Windows.
    await asyncio.sleep(0.25)


async def _extract_colors(page: Page) -> list[str]:
    """Extrai as 5 cores mais frequentes via CSS computado."""
    script = """
    () => {
        const colors = [];
        const elements = document.querySelectorAll('*');
        const limit = Math.min(elements.length, 500);
        for (let i = 0; i < limit; i++) {
            const style = window.getComputedStyle(elements[i]);
            const bg = style.backgroundColor;
            const color = style.color;
            if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                colors.push(bg);
            }
            if (color) colors.push(color);
        }
        return colors;
    }
    """
    try:
        raw_colors = await page.evaluate(script)
        counter = Counter(raw_colors)
        return [c for c, _ in counter.most_common(5)]
    except Exception:
        return []


async def _extract_fonts(page: Page) -> list[str]:
    """Detecta font-family do body e headings."""
    script = """
    () => {
        const fonts = new Set();
        const body = document.body;
        if (body) {
            fonts.add(window.getComputedStyle(body).fontFamily);
        }
        document.querySelectorAll('h1, h2, h3').forEach(el => {
            fonts.add(window.getComputedStyle(el).fontFamily);
        });
        return [...fonts];
    }
    """
    try:
        return await page.evaluate(script)
    except Exception:
        return []


def _parse_srcset(srcset: str) -> str | None:
    """Extrai a primeira URL de um atributo srcset."""
    if not srcset:
        return None
    first_entry = srcset.split(",")[0].strip()
    parts = first_entry.split()
    return parts[0] if parts else None


def _resolve_image_url(raw_url: str | None, page_url: str) -> str | None:
    """Resolve URL de imagem, ignorando data URIs."""
    if not raw_url or raw_url.startswith("data:"):
        return None
    return urljoin(page_url, raw_url)


async def _get_image_url(img, page_url: str) -> str | None:
    """Obtém URL real da imagem considerando lazy load (Elementor, etc.)."""
    for attr in ("data-src", "data-lazy-src", "src"):
        raw = await img.get_attribute(attr)
        resolved = _resolve_image_url(raw, page_url)
        if resolved:
            return resolved

    srcset = await img.get_attribute("srcset")
    if srcset:
        first = _parse_srcset(srcset)
        return _resolve_image_url(first, page_url)

    data_srcset = await img.get_attribute("data-srcset")
    if data_srcset:
        first = _parse_srcset(data_srcset)
        return _resolve_image_url(first, page_url)

    return None


async def _extract_images(page: Page, url: str) -> list[dict]:
    """Extrai imagens com suporte a lazy load (src, data-src, srcset)."""
    images: list[dict] = []
    seen_urls: set[str] = set()

    for img in await page.query_selector_all("img"):
        img_url = await _get_image_url(img, url)
        if not img_url or img_url in seen_urls:
            continue

        alt = await img.get_attribute("alt") or ""
        width = await img.get_attribute("width")
        height = await img.get_attribute("height")
        try:
            w = int(width) if width else 0
            h = int(height) if height else 0
        except ValueError:
            w, h = 0, 0

        if (w and w < 50) or (h and h < 50):
            bounding = await img.bounding_box()
            if bounding and (bounding["width"] < 50 or bounding["height"] < 50):
                continue

        seen_urls.add(img_url)
        images.append({
            "src": img_url,
            "alt": alt,
            "width": width,
            "height": height,
        })

    return images


async def _extract_page_content(page: Page, url: str) -> dict:
    """Extrai todos os dados estruturados de uma página renderizada."""
    texts: list[str] = []
    for selector in ["h1", "h2", "h3", "p", "li", "span"]:
        elements = await page.query_selector_all(selector)
        for el in elements:
            text = (await el.inner_text()).strip()
            if len(text) > 20:
                texts.append(text)

    images = await _extract_images(page, url)

    links: list[str] = []
    for a in await page.query_selector_all("a[href]"):
        href = await a.get_attribute("href")
        if href:
            links.append(urljoin(url, href))

    meta: dict[str, str] = {}
    title = await page.title()
    meta["title"] = title
    for name, attr in [
        ("description", "name"),
        ("og:title", "property"),
        ("og:description", "property"),
        ("og:image", "property"),
    ]:
        el = await page.query_selector(f'meta[{attr}="{name}"]')
        if el:
            content = await el.get_attribute("content")
            if content:
                meta[name] = content

    schema_ld: list[dict] = []
    scripts = await page.query_selector_all('script[type="application/ld+json"]')
    for script in scripts:
        content = await script.inner_text()
        if content:
            try:
                import json
                schema_ld.append(json.loads(content))
            except Exception:
                pass

    full_text = await page.inner_text("body")
    emails = list(set(EMAIL_PATTERN.findall(full_text)))
    phones = list(set(PHONE_PATTERN.findall(full_text)))

    addresses: list[str] = []
    for selector in [
        '[itemtype*="PostalAddress"]',
        '[class*="address"]',
        '[class*="contato"]',
        '[class*="localizacao"]',
        '[class*="localização"]',
        "address",
    ]:
        for el in await page.query_selector_all(selector):
            text = (await el.inner_text()).strip()
            if text and len(text) > 10:
                addresses.append(text)

    has_google_maps = False
    for iframe in await page.query_selector_all("iframe"):
        src = await iframe.get_attribute("src") or ""
        if "maps.google" in src or "google.com/maps" in src:
            has_google_maps = True
            break

    colors = await _extract_colors(page)
    fonts = await _extract_fonts(page)
    html = await page.content()

    return {
        "url": url,
        "texts": texts,
        "images": images,
        "links": links,
        "meta": meta,
        "schema_ld": schema_ld,
        "contacts": {
            "emails": emails,
            "phones": phones,
            "addresses": addresses,
            "whatsapp": "",
            "telefone": "",
            "telefones": [],
            "has_google_maps": has_google_maps,
        },
        "colors": colors,
        "fonts": fonts,
        "html": html,
    }


def _normalize_whatsapp(raw: str) -> str:
    """Normaliza número ou URL de WhatsApp para formato +55XXXXXXXXXXX."""
    if not raw:
        return ""

    match = WA_ME_PATTERN.search(raw)
    if match:
        num = match.group(1)
    else:
        api_match = re.search(r"phone=(\d{10,13})", raw)
        if api_match:
            num = api_match.group(1)
        else:
            digits = re.sub(r"\D", "", raw)
            if len(digits) >= 10:
                num = digits
            else:
                onclick_match = WA_ME_PATTERN.search(raw)
                num = onclick_match.group(1) if onclick_match else ""

    if not num:
        return ""

    if num.startswith("55") and len(num) >= 12:
        return f"+{num}"
    if len(num) in (10, 11):
        return f"+55{num}"
    return f"+{num}"


def _apply_contact_extraction(
    contacts: dict,
    js_results: dict,
    network_numbers: list[str],
    click_url: str | None = None,
) -> None:
    """Mescla contatos das formas A (JS), B (rede) e D (clique) no dict de contacts."""
    telefones: list[str] = list(contacts.get("telefones", []))
    telefones.extend(contacts.get("phones", []))

    whatsapp_candidates: list[str] = []

    if click_url:
        normalized = _normalize_whatsapp(click_url)
        if normalized:
            whatsapp_candidates.append(normalized)

    for key in ("whatsapp_url", "whatsapp_api", "whatsapp_data", "whatsapp_onclick"):
        value = js_results.get(key)
        if value:
            normalized = _normalize_whatsapp(str(value))
            if normalized:
                whatsapp_candidates.append(normalized)

    if js_results.get("phones"):
        telefones.extend(js_results["phones"])

    telefones.extend(network_numbers)

    if network_numbers and not whatsapp_candidates:
        whatsapp_candidates.append(network_numbers[0])

    if whatsapp_candidates and not contacts.get("whatsapp"):
        contacts["whatsapp"] = whatsapp_candidates[0]

    unique_phones = list(dict.fromkeys(t.strip() for t in telefones if t.strip()))
    if unique_phones:
        contacts["telefones"] = unique_phones[:5]
        if not contacts.get("telefone"):
            contacts["telefone"] = unique_phones[0]


async def _intercept_whatsapp_click(page: Page) -> str | None:
    """
    Tenta capturar URL do WhatsApp clicando em botões Elementor/popups.

    4ª tentativa: para botões que só revelam o link após clique ou popup.
    """
    captured: dict[str, str] = {}

    async def handle_popup(popup) -> None:
        try:
            popup_url = popup.url
            if popup_url and ("wa.me" in popup_url or "whatsapp" in popup_url):
                captured["url"] = popup_url
            await popup.close()
        except Exception:
            pass

    page.on("popup", handle_popup)

    selectors = [
        'a[href*="wa.me"]',
        'a[href*="whatsapp"]',
        'a[href*="api.whatsapp.com"]',
        '.elementor-button:has-text("WhatsApp")',
        'a:has-text("WhatsApp")',
        'a:has-text("Chamar")',
        'button:has-text("WhatsApp")',
        'button:has-text("Chamar")',
        'button:has-text("Iniciar Conversa")',
        '[class*="whatsapp"]',
    ]

    try:
        for selector in selectors:
            try:
                btn = await page.query_selector(selector)
                if not btn:
                    continue

                href = await btn.get_attribute("href")
                if href and ("wa.me" in href or "whatsapp" in href):
                    captured["url"] = href
                    break

                try:
                    await btn.click(timeout=3000, no_wait_after=True)
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass

                if captured.get("url"):
                    break
            except Exception:
                continue

        if not captured.get("url"):
            html = await page.content()
            wa_matches = WA_ME_PATTERN.findall(html)
            if wa_matches:
                captured["url"] = f"https://wa.me/{wa_matches[0]}"

    except Exception as exc:
        logger.debug("Falha ao interceptar clique WhatsApp: %s", exc)

    return captured.get("url")


async def scrape_page(
    url: str,
    screenshot_dir: Path | None = None,
    max_retries: int = 3,
    fast_mode: bool = False,
) -> dict | None:
    """
    Faz scraping de uma página com Playwright.

    fast_mode=True: timeout reduzido (10s), sem screenshot, sem espera longa.
    Usado na prospecção para ser mais rápido.
    """
    timeout = 10_000 if fast_mode else 30_000
    take_screenshot = not fast_mode
    screenshot_dir = screenshot_dir or (OUTPUT_DIR / "screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    domain = urlparse(url).netloc.replace("www.", "").replace(".", "_")
    safe_path = urlparse(url).path.replace("/", "_").strip("_") or "home"
    screenshot_path = screenshot_dir / f"{domain}_{safe_path}.png"

    for attempt in range(max_retries):
        context = None
        try:
            browser = await _get_browser()
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="pt-BR",
            )
            page = await context.new_page()

            whatsapp_numbers: list[str] = []

            def handle_request(request) -> None:
                req_url = request.url
                if "wa.me" in req_url or "whatsapp" in req_url.lower():
                    match = WA_ME_PATTERN.search(req_url)
                    if match:
                        num = match.group(1)
                        whatsapp_numbers.append(
                            f"+{num}" if num.startswith("55") else f"+55{num}"
                        )

            page.on("request", handle_request)

            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)

            if fast_mode:
                await page.wait_for_timeout(500)
            else:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)
                await asyncio.sleep(random.uniform(1, 3))

            data = await _extract_page_content(page, url)

            js_results = await page.evaluate(WHATSAPP_JS)

            click_url: str | None = None
            if not fast_mode and not (js_results or {}).get("whatsapp_url") and not whatsapp_numbers:
                click_url = await _intercept_whatsapp_click(page)

            _apply_contact_extraction(
                data["contacts"], js_results or {}, whatsapp_numbers, click_url
            )

            if take_screenshot:
                await page.screenshot(full_page=True, path=str(screenshot_path))
                data["screenshot_path"] = str(screenshot_path)
            else:
                data["screenshot_path"] = ""

            return data

        except Exception as exc:
            wait = 2 ** attempt
            logger.warning(
                "Tentativa %d/%d falhou para %s: %s. Aguardando %ds...",
                attempt + 1, max_retries, url, exc, wait,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)
            else:
                logger.error("Falha definitiva ao scrapear %s", url)
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

    return None
