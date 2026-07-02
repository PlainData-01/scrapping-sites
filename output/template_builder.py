"""Construtor de protótipos a partir de templates HTML estáticos."""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR
from output.site_generator import SiteGeneratorInput, TEMPLATES_DIR
from prospector.icp_loader import load_icp

logger = logging.getLogger(__name__)

VARIATIONS: dict[str, list[str]] = {
    "odontologia-premium": [
        "premium_minimal", "familiar", "implantes", "ortodontia", "local_acessivel",
    ],
    "estetica-premium": ["premium_transformacao", "humanizada", "procedimento_rapido"],
    "advocacia-local": ["autoridade_institucional", "captacao_area", "escritorio_local"],
    "restaurante-local": ["experiencia_gastronomica", "delivery_cardapio", "reservas_eventos"],
    "servico-local": ["orcamento_rapido", "emergencia_rapidez", "confianca_local"],
}


def _slug(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"[\s_]+", "-", s)[:40] or "empresa"


async def build_from_template(input_data: SiteGeneratorInput) -> dict[str, str]:
    """Gera landing page HTML a partir de template + dados do lead."""
    icp = load_icp(input_data.icp_id)
    template_id = input_data.template_id or icp.recommended_prototype
    template_dir = TEMPLATES_DIR / template_id

    if not template_dir.exists():
        template_dir = TEMPLATES_DIR / "odontologia-premium"

    config = _load_json(template_dir / "template.config.json")
    sections = _load_json(template_dir / "sections.json")
    tokens = _load_json(template_dir / "style_tokens.json")
    copy_schema = _load_json(template_dir / "copy_schema.json")

    variations = VARIATIONS.get(template_id, ["default"])
    variation = input_data.variation or random.choice(variations)

    lead = input_data.lead
    analysis = input_data.analysis
    site_data = input_data.site_data

    business_name = (
        lead.get("nome")
        or analysis.get("business_name")
        or site_data.domain
    )
    whatsapp = (
        lead.get("whatsapp")
        or site_data.contacts.get("whatsapp", "")
        or lead.get("telefone", "")
    )
    whatsapp_digits = re.sub(r"\D", "", whatsapp)
    cidade = lead.get("city") or _extract_city(lead.get("endereco", ""))
    oferta = lead.get("suggested_offer") or icp.offer.get("type", "")
    dor = lead.get("main_pain") or lead.get("problema_principal", "")

    copy = _build_copy(copy_schema, business_name, cidade, oferta, dor, variation)
    html = _render_page(config, sections, tokens, copy, whatsapp_digits, variation, template_id)

    domain_slug = site_data.domain.replace(".", "_")
    out_dir = OUTPUT_DIR / "sites" / domain_slug / "prototype"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")

    from output.quality_checklist import run_quality_check
    quality = run_quality_check(
        html,
        business_name=business_name,
        whatsapp=whatsapp_digits,
        niche=icp.id,
        variation=variation,
        output_dir=out_dir,
    )

    meta_path = out_dir / "prototype.meta.json"
    meta_path.write_text(
        json.dumps({
            "template_id": template_id,
            "variation": variation,
            "business_name": business_name,
            "icp_id": icp.id,
            "quality": quality,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "output_path": str(out_path),
        "preview_url": f"/prototype/{domain_slug}",
        "template_id": template_id,
        "variation": variation,
        "quality_report": quality,
    }


def _load_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_city(endereco: str) -> str:
    if not endereco:
        return "sua cidade"
    parts = [p.strip() for p in endereco.split(",")]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _build_copy(
    schema: dict,
    name: str,
    city: str,
    offer: str,
    pain: str,
    variation: str,
) -> dict[str, Any]:
    hero = schema.get("hero", {})
    cta = schema.get("cta", {})

    headline_tpl = hero.get("headlines", {}).get(variation) or hero.get("headlines", {}).get("default", "")
    sub_tpl = hero.get("subheadlines", {}).get(variation) or hero.get("subheadlines", {}).get("default", "")

    cta = schema.get("cta", {})
    cta_primary = cta.get(variation) or cta.get("primary", "Agendar pelo WhatsApp")

    services = (schema.get("services_by_variation") or {}).get(variation) or schema.get("services", [])
    journey = schema.get("journey_steps", [])

    return {
        "business_name": name,
        "city": city,
        "headline": headline_tpl.format(name=name, city=city),
        "subheadline": sub_tpl.format(name=name, city=city, offer=offer, pain=pain or "melhorar seus resultados online"),
        "cta_text": cta_primary,
        "cta_secondary": cta.get("secondary", "Fale conosco"),
        "services": services,
        "trust_items": schema.get("trust_items", []),
        "differentials": [
            {**d, "text": d.get("text", "").format(city=city, name=name)}
            for d in schema.get("differentials", [])
        ],
        "journey_steps": journey,
        "offer": offer,
    }


def _render_page(
    config: dict,
    sections: dict,
    tokens: dict,
    copy: dict,
    whatsapp: str,
    variation: str,
    template_id: str = "",
) -> str:
    order = sections.get("orders", {}).get(variation) or sections.get("orders", {}).get("default", [])
    vtokens = (tokens.get("variations") or {}).get(variation) or {}
    colors = {**(tokens.get("colors") or {}), **(vtokens.get("colors") or {})}
    fonts = {**(tokens.get("fonts") or {}), **(vtokens.get("fonts") or {})}
    primary = colors.get("primary", "#0d9488")
    accent = colors.get("accent", "#f59e0b")
    bg = colors.get("background", "#fafafa")
    text = colors.get("text", "#1e293b")
    font_heading = fonts.get("heading", "Georgia, serif")
    font_body = fonts.get("body", "system-ui, sans-serif")
    hero_style = vtokens.get("hero_style", "centered")

    wa_url = f"https://wa.me/{whatsapp}" if whatsapp else "#"

    parts: list[str] = []
    for section_id in order:
        renderer = _SECTION_RENDERERS.get(section_id)
        if renderer:
            parts.append(renderer(copy, wa_url, primary, accent, hero_style=hero_style))

    body = "\n".join(parts)
    niche_label = config.get("niche_label", "Prospect Hub")
    extra_css = _variation_css(variation, primary, bg)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{copy["business_name"]} — {niche_label}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: {font_body}; color: {text}; background: {bg}; line-height: 1.6; }}
    h1, h2, h3 {{ font-family: {font_heading}; }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 0 1.25rem; }}
    .btn {{ display: inline-block; padding: 0.85rem 1.75rem; border-radius: 8px; font-weight: 600; text-decoration: none; transition: opacity .2s; }}
    .btn:hover {{ opacity: 0.9; }}
    .btn-primary {{ background: {primary}; color: #fff; }}
    .btn-accent {{ background: {accent}; color: #fff; }}
    section {{ padding: 4rem 0; }}
    .hero {{ padding: 5rem 0; background: linear-gradient(135deg, {primary}15, {accent}10); }}
    .hero h1 {{ font-size: clamp(1.75rem, 4vw, 2.75rem); margin-bottom: 1rem; }}
    .hero p {{ font-size: 1.15rem; opacity: 0.85; max-width: 560px; margin-bottom: 1.5rem; }}
    .grid {{ display: grid; gap: 1.5rem; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .card {{ background: #fff; border-radius: 12px; padding: 1.5rem; box-shadow: 0 2px 12px rgba(0,0,0,.06); }}
    .card h3 {{ margin-bottom: 0.5rem; color: {primary}; }}
    .trust {{ background: {primary}08; }}
    .cta-section {{ text-align: center; background: {primary}; color: #fff; }}
    .cta-section .btn {{ background: #fff; color: {primary}; }}
    .float-wa {{ position: fixed; bottom: 1.5rem; right: 1.5rem; z-index: 99; }}
    .float-wa a {{ background: #25d366; color: #fff; padding: 1rem 1.25rem; border-radius: 50px; text-decoration: none; font-weight: 600; box-shadow: 0 4px 20px rgba(37,211,102,.4); }}
    footer {{ padding: 2rem 0; text-align: center; opacity: 0.6; font-size: 0.875rem; }}
    {extra_css}
  </style>
</head>
<body>
{body}
<div class="float-wa"><a href="{wa_url}" target="_blank" rel="noopener">WhatsApp</a></div>
<footer><div class="container">Protótipo gerado pelo Prospect Hub — {copy["business_name"]}</div></footer>
</body>
</html>"""


def _variation_css(variation: str, primary: str, bg: str) -> str:
    if variation == "premium_minimal":
        return f".hero {{ background: {bg}; padding: 6rem 0; }} .hero h1 {{ font-weight: 400; letter-spacing: -0.02em; }}"
    if variation == "ortodontia":
        return ".hero { border-bottom: 4px solid var(--accent, #6366f1); } .card { border-radius: 16px; }"
    if variation == "local_acessivel":
        return ".hero { background: linear-gradient(180deg, #f0fdf4, #fff); } .btn-primary { border-radius: 999px; }"
    if variation == "premium_transformacao":
        return f".hero {{ background: linear-gradient(160deg, {primary}18, #fff); }} .card {{ border: 1px solid {primary}22; }}"
    if variation == "humanizada":
        return ".hero { border-radius: 0 0 48px 48px; } .btn-primary { border-radius: 999px; }"
    if variation == "procedimento_rapido":
        return ".hero h1 { font-size: clamp(1.5rem, 3.5vw, 2.25rem); } .cta-section { border-radius: 16px; margin: 2rem 1rem; }"
    if variation == "autoridade_institucional":
        return f".hero {{ border-left: 6px solid {primary}; }} h1 {{ text-transform: uppercase; letter-spacing: .04em; font-size: 1.85rem; }}"
    if variation == "captacao_area":
        return ".hero { background: #0f172a; color: #f8fafc; } .hero p { color: #cbd5e1; }"
    if variation == "escritorio_local":
        return f".hero {{ background: linear-gradient(135deg, {primary}12, #f8fafc); }} .card {{ box-shadow: none; border: 1px solid #e2e8f0; }}"
    if variation == "experiencia_gastronomica":
        return f".hero {{ background: radial-gradient(circle at top, {primary}22, {bg}); }} .btn-primary {{ border-radius: 4px; }}"
    if variation == "delivery_cardapio":
        return ".hero { text-align: center; } .btn-primary { border-radius: 999px; font-size: 1.05rem; }"
    if variation == "reservas_eventos":
        return f".hero {{ background: {primary}; color: #fff; }} .hero p {{ color: rgba(255,255,255,.9); }} .hero .btn-primary {{ background: #fff; color: {primary}; }}"
    if variation == "orcamento_rapido":
        return ".hero { padding: 3.5rem 0; } .grid { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }"
    if variation == "emergencia_rapidez":
        return f".hero {{ background: #fef2f2; border-bottom: 3px solid {primary}; }} .btn-primary {{ animation: pulse 2s infinite; }}"
    if variation == "confianca_local":
        return f".trust {{ background: {primary}10; border-top: 1px solid {primary}30; }}"
    return ""


def _render_hero(copy: dict, wa_url: str, primary: str, accent: str, hero_style: str = "centered") -> str:
    if hero_style == "split":
        return f"""
<section class="hero" style="display:grid;grid-template-columns:1fr 1fr;gap:2rem;align-items:center">
  <div class="container" style="max-width:none;padding:3rem 2rem">
    <p style="text-transform:uppercase;letter-spacing:.1em;font-size:.75rem;color:{primary};margin-bottom:.75rem">Avaliação sem compromisso</p>
    <h1>{copy["headline"]}</h1>
    <p>{copy["subheadline"]}</p>
    <a class="btn btn-primary" href="{wa_url}">{copy["cta_text"]}</a>
  </div>
  <div style="background:{primary}12;min-height:280px;border-radius:0 0 0 80px"></div>
</section>"""
    if hero_style == "minimal":
        return f"""
<section class="hero" style="text-align:center;padding:7rem 0 5rem">
  <div class="container" style="max-width:640px">
    <h1 style="font-weight:400">{copy["headline"]}</h1>
    <p style="margin:1.25rem auto 2rem">{copy["subheadline"]}</p>
    <a class="btn btn-primary" href="{wa_url}">{copy["cta_text"]}</a>
  </div>
</section>"""
    return f"""
<section class="hero">
  <div class="container">
    <h1>{copy["headline"]}</h1>
    <p>{copy["subheadline"]}</p>
    <a class="btn btn-primary" href="{wa_url}">{copy["cta_text"]}</a>
  </div>
</section>"""


def _render_services(copy: dict, wa_url: str, primary: str, accent: str, **_) -> str:
    cards = "".join(
        f'<div class="card"><h3>{s.get("title","")}</h3><p>{s.get("description","")}</p></div>'
        for s in copy.get("services", [])[:6]
    )
    return f'<section><div class="container"><h2 style="margin-bottom:1.5rem;text-align:center">Nossos serviços</h2><div class="grid">{cards}</div></div></section>'


def _render_trust(copy: dict, wa_url: str, primary: str, accent: str, **_) -> str:
    items = "".join(f'<div class="card"><p>{t}</p></div>' for t in copy.get("trust_items", [])[:4])
    return f'<section class="trust"><div class="container"><h2 style="margin-bottom:1.5rem;text-align:center">Por que confiar</h2><div class="grid">{items}</div></div></section>'


def _render_differentials(copy: dict, wa_url: str, primary: str, accent: str, **_) -> str:
    items = "".join(
        f'<div class="card"><h3>{d.get("title","")}</h3><p>{d.get("text","")}</p></div>'
        for d in copy.get("differentials", [])[:4]
    )
    return f'<section><div class="container"><h2 style="margin-bottom:1.5rem;text-align:center">Diferenciais</h2><div class="grid">{items}</div></div></section>'


def _render_cta(copy: dict, wa_url: str, primary: str, accent: str, **_) -> str:
    return f"""
<section class="cta-section">
  <div class="container">
    <h2 style="margin-bottom:1rem">Pronto para começar?</h2>
    <p style="margin-bottom:1.5rem;opacity:.9">{copy.get("offer", "")}</p>
    <a class="btn" href="{wa_url}">{copy["cta_text"]}</a>
  </div>
</section>"""


def _render_contact(copy: dict, wa_url: str, primary: str, accent: str, **_) -> str:
    return f"""
<section>
  <div class="container" style="text-align:center">
    <h2 style="margin-bottom:1rem">Fale conosco</h2>
    <p style="margin-bottom:1.5rem">{copy["business_name"]} — {copy["city"]}</p>
    <a class="btn btn-accent" href="{wa_url}">{copy["cta_secondary"]}</a>
  </div>
</section>"""


def _render_journey(copy: dict, wa_url: str, primary: str, accent: str, **_) -> str:
    steps = copy.get("journey_steps") or [
        {"title": "1. Contato", "text": "Fale conosco pelo WhatsApp"},
        {"title": "2. Avaliação", "text": "Entendemos sua necessidade"},
        {"title": "3. Plano", "text": "Proposta personalizada"},
        {"title": "4. Resultado", "text": "Acompanhamento contínuo"},
    ]
    items = "".join(
        f'<div class="card"><h3>{s["title"]}</h3><p>{s["text"]}</p></div>' for s in steps[:4]
    )
    return f'<section><div class="container"><h2 style="margin-bottom:1.5rem;text-align:center">Como funciona</h2><div class="grid">{items}</div></div></section>'


_SECTION_RENDERERS = {
    "hero": _render_hero,
    "services": _render_services,
    "trust": _render_trust,
    "differentials": _render_differentials,
    "journey": _render_journey,
    "cta": _render_cta,
    "contact": _render_contact,
}
