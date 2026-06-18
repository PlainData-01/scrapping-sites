"""Descoberta de páginas via sitemap e BFS com respeito ao robots.txt."""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from config import BINARY_EXTENSIONS, CRAWL_DELAY_SECONDS, MAX_PAGES_PER_SITE, USER_AGENT

logger = logging.getLogger(__name__)

SITEMAP_INDEX_PATHS = [
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
    "/sitemap.xml",
]

INSTITUTIONAL_SLUGS = frozenset({
    "sobre", "empresa", "quem-somos", "institucional", "about",
    "servicos", "serviços", "services", "produtos", "products",
    "contato", "contact", "fale-conosco", "localizacao", "localização",
    "equipe", "time", "portfolio", "portifolio", "trabalhos",
    "orcamento", "orçamento", "agendamento", "home", "inicio", "início",
})

BLOG_PATH_PATTERNS = re.compile(
    r"/(?:blog|category|categorias|tag|tags|author|autor|archive|arquivo|feed|wp-json)(?:/|$)"
    r"|\d{4}/\d{2}/",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    """Normaliza URL removendo fragmentos e trailing slashes."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def _is_same_domain(base_url: str, url: str) -> bool:
    """Verifica se a URL pertence ao mesmo domínio."""
    base_netloc = urlparse(base_url).netloc.replace("www.", "")
    url_netloc = urlparse(url).netloc.replace("www.", "")
    return base_netloc == url_netloc


def _is_valid_internal_url(base_url: str, url: str) -> bool:
    """Filtra URLs inválidas, externas ou binárias."""
    if not url or url.startswith(("#", "mailto:", "tel:", "javascript:")):
        return False

    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return False

    full_url = urljoin(base_url, url)
    if not _is_same_domain(base_url, full_url):
        return False

    path_lower = urlparse(full_url).path.lower()
    for ext in BINARY_EXTENSIONS:
        if path_lower.endswith(ext):
            return False

    return True


def _looks_like_blog_post(url: str) -> bool:
    """
    Identifica URLs que parecem posts de blog.

    Posts WordPress costumam ser /slug-longo sem subdiretório institucional,
    ou paths com /blog/, /category/, datas, etc.
    """
    parsed = urlparse(url)
    path = parsed.path.lower()

    if path in ("/", ""):
        return False

    if BLOG_PATH_PATTERNS.search(path):
        return True

    segments = [s for s in path.split("/") if s]

    if len(segments) >= 2:
        first = segments[0]
        if first in ("blog", "category", "categorias", "tag", "tags", "author", "autor"):
            return True
        if first.isdigit() and len(first) == 4:
            return True

    if len(segments) == 1:
        slug = segments[0]
        if slug in INSTITUTIONAL_SLUGS:
            return False
        if "-" in slug and len(slug) > 20:
            return True
        if re.match(r"^\d+$", slug):
            return True

    return False


def extract_nav_links(html: str, base_url: str) -> list[str]:
    """
    Extrai links do <nav> ou menu principal da página.

    Busca em nav, header, role=navigation e classes comuns de menu WordPress.
    """
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()

    nav_selectors = [
        "nav",
        "header nav",
        '[role="navigation"]',
        ".main-navigation",
        ".primary-menu",
        ".primary-navigation",
        "#primary-menu",
        "#main-navigation",
        ".menu-principal",
        ".navbar",
        "header .menu",
        "#menu",
        ".elementor-nav-menu",
    ]

    containers: list = []
    for selector in nav_selectors:
        containers.extend(soup.select(selector))

    if not containers:
        header = soup.find("header")
        if header:
            containers.append(header)

    for container in containers:
        for tag in container.find_all("a", href=True):
            href = tag["href"].strip()
            if _is_valid_internal_url(base_url, href):
                full = _normalize_url(urljoin(base_url, href))
                if full not in seen:
                    seen.add(full)
                    links.append(full)

    return links


def _get_robots_parser(base_url: str) -> RobotFileParser:
    """Carrega e parseia robots.txt do site."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception as exc:
        logger.warning("Não foi possível ler robots.txt: %s", exc)
    return rp


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    """Baixa conteúdo textual de uma URL."""
    try:
        response = await client.get(url, follow_redirects=True)
        if response.status_code == 200:
            return response.text
    except Exception as exc:
        logger.debug("Falha ao buscar %s: %s", url, exc)
    return None


def _parse_sitemap_xml(content: str, base_url: str) -> list[str]:
    """Extrai URLs de um arquivo sitemap XML."""
    urls: list[str] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return urls

    namespaces = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for loc in root.findall(".//sm:loc", namespaces):
        if loc.text:
            urls.append(_normalize_url(loc.text.strip()))

    if not urls:
        for loc in root.findall(".//loc"):
            if loc.text:
                urls.append(_normalize_url(loc.text.strip()))

    return [u for u in urls if _is_valid_internal_url(base_url, u)]


def _parse_sitemap_index(content: str) -> list[str]:
    """Extrai URLs de sitemaps filhos de um sitemap index."""
    child_sitemaps: list[str] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return child_sitemaps

    namespaces = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for loc in root.findall(".//sm:sitemap/sm:loc", namespaces):
        if loc.text:
            child_sitemaps.append(loc.text.strip())

    if not child_sitemaps:
        for loc in root.findall(".//sitemap/loc"):
            if loc.text:
                child_sitemaps.append(loc.text.strip())

    return child_sitemaps


def _sitemap_priority(sitemap_url: str) -> int:
    """Menor valor = maior prioridade. page-sitemap antes de post-sitemap."""
    url_lower = sitemap_url.lower()
    if "page-sitemap" in url_lower or "page_sitemap" in url_lower:
        return 0
    if "wp-sitemap-posts-page" in url_lower:
        return 0
    if "post-sitemap" in url_lower or "post_sitemap" in url_lower:
        return 10
    if any(k in url_lower for k in ("category-sitemap", "tag-sitemap", "author-sitemap")):
        return 20
    return 5


def _is_page_sitemap(sitemap_url: str) -> bool:
    """Verifica se o sitemap filho é de páginas WordPress."""
    url_lower = sitemap_url.lower()
    return (
        "page-sitemap" in url_lower
        or "page_sitemap" in url_lower
        or "wp-sitemap-posts-page" in url_lower
    )


async def _discover_from_sitemap(
    client: httpx.AsyncClient, base_url: str
) -> list[str]:
    """
    Descobre páginas via sitemap index priorizando page-sitemap.xml.

    Se não houver page-sitemap, retorna lista vazia para acionar BFS.
    """
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    child_sitemaps: list[str] = []
    direct_urls: list[str] = []

    for sitemap_path in SITEMAP_INDEX_PATHS:
        sitemap_url = urljoin(origin, sitemap_path)
        content = await _fetch_text(client, sitemap_url)
        if not content:
            continue

        is_index = (
            "sitemapindex" in content.lower()
            or "<sitemap>" in content.lower()
        )

        if is_index:
            child_sitemaps = _parse_sitemap_index(content)
            if child_sitemaps:
                logger.info(
                    "Sitemap index encontrado com %d sitemaps filhos",
                    len(child_sitemaps),
                )
                break
        else:
            direct_urls = _parse_sitemap_xml(content, base_url)
            if direct_urls:
                logger.info("Sitemap direto encontrado com %d URLs", len(direct_urls))
                break

    if child_sitemaps:
        sorted_sitemaps = sorted(child_sitemaps, key=_sitemap_priority)
        page_sitemaps = [s for s in sorted_sitemaps if _is_page_sitemap(s)]

        if not page_sitemaps:
            logger.info(
                "page-sitemap.xml não encontrado — BFS será usado como fallback"
            )
            return []

        discovered: list[str] = []
        for sitemap_url in page_sitemaps:
            sub_content = await _fetch_text(client, sitemap_url)
            if sub_content:
                urls = _parse_sitemap_xml(sub_content, base_url)
                discovered.extend(urls)
                logger.info(
                    "page-sitemap %s: %d URLs", sitemap_url, len(urls)
                )

        for sitemap_url in sorted_sitemaps:
            if _is_page_sitemap(sitemap_url):
                continue
            if _sitemap_priority(sitemap_url) >= 10:
                continue
            sub_content = await _fetch_text(client, sitemap_url)
            if sub_content:
                discovered.extend(_parse_sitemap_xml(sub_content, base_url))

        return list(dict.fromkeys(discovered))

    if direct_urls:
        non_blog = [u for u in direct_urls if not _looks_like_blog_post(u)]
        return non_blog if non_blog else direct_urls

    return []


def _extract_links_from_html(html: str, base_url: str) -> list[str]:
    """Extrai links internos do HTML para alimentar o BFS."""
    links: list[str] = []
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if _is_valid_internal_url(base_url, href):
            full = _normalize_url(urljoin(base_url, href))
            links.append(full)
    return links


async def _discover_bfs(
    client: httpx.AsyncClient,
    base_url: str,
    robots: RobotFileParser,
    max_pages: int,
) -> list[str]:
    """Descobre páginas via BFS a partir da URL raiz."""
    normalized_base = _normalize_url(base_url)
    queue: deque[str] = deque([normalized_base])
    visited: set[str] = set()
    discovered: list[str] = []

    while queue and len(discovered) < max_pages:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        if not robots.can_fetch(USER_AGENT, current):
            logger.debug("Bloqueado por robots.txt: %s", current)
            continue

        content = await _fetch_text(client, current)
        if content is None:
            continue

        if not _looks_like_blog_post(current):
            discovered.append(current)

        for link in _extract_links_from_html(content, base_url):
            if link not in visited and link not in queue and not _looks_like_blog_post(link):
                queue.append(link)

        await asyncio.sleep(CRAWL_DELAY_SECONDS)

    return discovered


def _prioritize_pages(
    pages: list[str],
    base_url: str,
    nav_links: list[str],
) -> list[str]:
    """Coloca home e links do menu no início da lista."""
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    home_urls = {_normalize_url(origin + "/"), _normalize_url(base_url)}

    priority: list[str] = []
    seen: set[str] = set()

    for url in list(home_urls) + nav_links:
        if url in seen:
            continue
        if url in pages or any(
            _normalize_url(p) == url for p in pages
        ):
            priority.append(url)
            seen.add(url)

    for url in pages:
        if url not in seen:
            priority.append(url)
            seen.add(url)

    return priority


async def get_all_pages(base_url: str, max_pages: int | None = None) -> list[str]:
    """
    Descobre páginas internas priorizando institucionais sobre posts de blog.

    Usa page-sitemap quando disponível; caso contrário, BFS a partir da home.
    Sempre inclui a home e links do menu principal.
    """
    limit = max_pages or MAX_PAGES_PER_SITE
    parsed = urlparse(base_url)
    if not parsed.scheme:
        base_url = f"https://{base_url}"

    normalized_base = _normalize_url(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    home_url = _normalize_url(origin + "/")
    robots = _get_robots_parser(normalized_base)

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(
        headers=headers, timeout=15.0, follow_redirects=True
    ) as client:
        pages = await _discover_from_sitemap(client, normalized_base)

        if not pages:
            logger.info("Iniciando BFS a partir da home: %s", home_url)
            pages = await _discover_bfs(client, home_url, robots, limit)

        pages = [p for p in pages if robots.can_fetch(USER_AGENT, p)]
        pages = [p for p in pages if not _looks_like_blog_post(p)]

        home_html = await _fetch_text(client, home_url)
        nav_links: list[str] = []
        if home_html:
            nav_links = extract_nav_links(home_html, base_url)
            logger.info("Links do menu principal: %d", len(nav_links))

        pages = _prioritize_pages(pages, base_url, nav_links)

        if home_url not in pages:
            pages.insert(0, home_url)

        for nav_url in reversed(nav_links):
            if nav_url not in pages:
                pages.insert(1, nav_url)

    unique_pages = list(dict.fromkeys(pages))[:limit]
    logger.info("Descobertas %d páginas para %s", len(unique_pages), normalized_base)
    return unique_pages
