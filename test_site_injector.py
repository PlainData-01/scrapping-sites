"""Testes unitários do site_injector — sanidade e parametrização por cliente."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from config import SiteData
from output.site_injector import (
    generate_constants_ts,
    generate_hero_ts,
    inject_scraped_content,
    validate_injection_sanity,
)


def _genforce_site_data() -> SiteData:
    sd = SiteData(url="https://www.genforce.com.br")
    sd.domain = "genforce.com.br"
    sd.pages = [
        {
            "url": "https://www.genforce.com.br/",
            "page_type": "home",
            "texts": ["Grupos geradores de energia", "30 anos de experiência"],
            "images": [
                {"src": "https://www.genforce.com.br/img/gerador.jpg", "alt": "Grupo gerador Genforce"},
            ],
        }
    ]
    sd.contacts = {"cidade": "Brasília", "whatsapp": "61999999999"}
    return sd


def _genforce_analysis() -> dict:
    return {
        "business_name": "Genforce",
        "business_type": "Empresa de grupos geradores e energia",
        "business_description": "Soluções em grupos geradores e energia de backup para empresas.",
        "value_proposition": "Energia confiável com grupos geradores",
        "niche_category": "industrial_b2b",
    }


def test_genforce_constants_nao_contem_odontologia() -> None:
    content = generate_constants_ts(_genforce_site_data(), _genforce_analysis())
    lower = content.lower()
    assert "odontolog" not in lower
    assert "viviane" not in lower
    assert "draviviane" not in lower
    assert "genforce" in lower
    assert "gerador" in lower or "energia" in lower


def test_hero_ts_usa_constants_dinamicos() -> None:
    hero = generate_hero_ts()
    assert "HERO.titulo" in hero
    assert "IMAGENS.hero" in hero
    assert "Odontologia" not in hero
    assert "draViviane" not in hero
    assert "SEM_CONVENIO" not in hero


def test_validate_sanity_rejeita_genforce_com_conteudo_dental() -> None:
    dental_content = "Odontologia de alto padrão — draViviane em Brasília"
    with pytest.raises(ValueError, match="genforce|odontolog|contaminação"):
        validate_injection_sanity(
            "genforce.com.br",
            _genforce_analysis(),
            dental_content,
        )


def test_validate_sanity_aceita_genforce_correto() -> None:
    content = generate_constants_ts(_genforce_site_data(), _genforce_analysis())
    validate_injection_sanity("genforce.com.br", _genforce_analysis(), content)


def test_inject_cria_arco_e_hero_parametrizado() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / "lib").mkdir()
        written = inject_scraped_content(str(project), _genforce_site_data(), _genforce_analysis())

        assert "components/ui/Arco.tsx" in written
        assert "components/home/Hero.tsx" in written

        hero = (project / "components" / "home" / "Hero.tsx").read_text(encoding="utf-8")
        constants = (project / "lib" / "constants.ts").read_text(encoding="utf-8")
        arco = (project / "components" / "ui" / "Arco.tsx").read_text(encoding="utf-8")

        assert "Odontologia" not in hero
        assert "Genforce" in constants
        assert "export function Arco" in arco
        assert "export function ArcoMini" in arco
