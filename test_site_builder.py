"""Script de diagnóstico isolado para build_site() — sem rodar o pipeline inteiro."""

from __future__ import annotations

import asyncio
import logging

from config import SiteData
from output.briefing_export import _enrich_known_contacts
from output.site_builder import build_site

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


async def test() -> None:
    site_data = SiteData(url="https://dravivianeamaral.com.br")
    site_data.domain = "dravivianeamaral.com.br"
    _enrich_known_contacts(site_data)
    analysis = {
        "business_name": "Clínica Viviane Amaral",
        "business_type": "Clínica odontológica premium",
        "business_description": "Odontologia de alto padrão em Brasília desde 1994.",
        "niche_category": "saude_premium",
    }
    briefing_path = "output/briefings/dravivianeamaral_com_br_briefing.md"

    project_path, post_status = await build_site(site_data, analysis, briefing_path)
    print(f"\nResultado: {project_path}")
    print(f"Status: {post_status}")
    print("Dados e fotos do scraping são injetados automaticamente em lib/constants.ts e lib/images.ts")


if __name__ == "__main__":
    asyncio.run(test())
