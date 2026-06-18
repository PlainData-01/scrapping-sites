"""Download de imagens e assets do site."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

from config import USER_AGENT

logger = logging.getLogger(__name__)

MIN_IMAGE_SIZE_BYTES = 10 * 1024
MAX_IMAGES = 30


def _url_to_filename(url: str) -> str:
    """Gera nome de arquivo baseado em hash MD5 da URL."""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
        ext = ".jpg"
    return f"{url_hash}{ext}"


async def download_assets(
    image_urls: list[str],
    output_dir: str | Path,
) -> dict[str, str]:
    """
    Baixa imagens relevantes (>10KB) e retorna mapeamento url -> caminho local.

    Limita a 30 imagens por site.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    mapping: dict[str, str] = {}
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(
        headers=headers, timeout=10.0, follow_redirects=True
    ) as client:
        for url in image_urls[:MAX_IMAGES]:
            if url in mapping:
                continue
            try:
                response = await client.get(url)
                if response.status_code != 200:
                    continue

                content = response.content
                if len(content) < MIN_IMAGE_SIZE_BYTES:
                    logger.debug("Imagem ignorada (<10KB): %s", url)
                    continue

                filename = _url_to_filename(url)
                filepath = output_path / filename
                filepath.write_bytes(content)
                mapping[url] = str(filepath)
                logger.debug("Asset baixado: %s -> %s", url, filepath)

            except Exception as exc:
                logger.warning("Falha ao baixar asset %s: %s", url, exc)

    logger.info("Baixados %d assets de %d URLs", len(mapping), len(image_urls))
    return mapping
