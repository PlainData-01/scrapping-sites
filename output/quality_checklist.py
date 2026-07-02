"""Checklist automático de qualidade para protótipos gerados."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


GENERIC_PHRASES = [
    "soluções inovadoras para sua empresa",
    "lorem ipsum",
    "sua empresa aqui",
    "empresa exemplo",
    "clique aqui",
]

CRITICAL_IDS = frozenset({
    "business_name_present",
    "html_exists",
    "cta_visible",
    "no_lorem",
    "niche_section",
})


def run_quality_check(
    html: str,
    *,
    business_name: str,
    whatsapp: str = "",
    niche: str = "",
    variation: str = "",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Executa checklist e opcionalmente salva quality_report.json."""
    html_lower = html.lower()
    name_ok = bool(business_name) and business_name.lower() in html_lower

    checks: list[dict[str, Any]] = [
        {"id": "business_name_present", "label": "Nome da empresa no conteúdo", "passed": name_ok, "critical": True},
        {"id": "html_exists", "label": "HTML gerado", "passed": len(html) > 200, "critical": True},
        {"id": "whatsapp_link", "label": "Link WhatsApp", "passed": "wa.me" in html_lower or not whatsapp, "critical": False},
        {"id": "cta_visible", "label": "CTA principal visível", "passed": "whatsapp" in html_lower or "agendar" in html_lower or "btn" in html_lower, "critical": True},
        {"id": "no_lorem", "label": "Sem Lorem ipsum", "passed": "lorem ipsum" not in html_lower, "critical": True},
        {"id": "no_placeholders", "label": "Sem placeholders óbvios", "passed": not any(p in html_lower for p in GENERIC_PHRASES if p != "lorem ipsum"), "critical": False},
        {"id": "no_fake_stats", "label": "Sem blocos de números inventados", "passed": not _has_fake_stats(html), "critical": False},
        {"id": "niche_section", "label": "Seção específica do nicho", "passed": _has_niche_content(html_lower, niche), "critical": True},
        {"id": "value_proposition", "label": "Proposta de valor clara", "passed": len(re.findall(r"<h[12][^>]*>", html, re.I)) >= 1, "critical": False},
        {"id": "responsive_meta", "label": "Viewport mobile", "passed": "viewport" in html_lower, "critical": False},
        {"id": "variation_logged", "label": "Variação registrada", "passed": bool(variation), "critical": False},
    ]

    passed = sum(1 for c in checks if c["passed"])
    critical_failures = [c for c in checks if c.get("critical") and not c["passed"]]
    ready = len(critical_failures) == 0

    report: dict[str, Any] = {
        "ready_to_send": ready,
        "passed": passed,
        "total": len(checks),
        "critical_failures": [c["label"] for c in critical_failures],
        "warning": "" if ready else "Protótipo gerado, mas precisa de revisão antes de enviar.",
        "checks": checks,
        "variation": variation,
        "niche": niche,
    }

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "quality_report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(path)

    return report


def _has_fake_stats(html: str) -> bool:
    """Detecta faixas típicas de números genéricos de IA."""
    patterns = [
        r"\d{2,4}\+?\s*(clientes|pacientes|anos|projetos)",
        r"\d{1,2}\s*%\s*de\s*satisfação",
        r"mais de \d{3,}",
    ]
    return any(re.search(p, html, re.I) for p in patterns)


def _has_niche_content(html: str, niche: str) -> bool:
    keywords = {
        "odontologia": ["dente", "odont", "sorriso", "clareamento", "implante"],
        "estetica": ["estética", "procedimento", "harmonização", "facial"],
        "advocacia": ["advogad", "jurídic", "direito", "escritório"],
        "restaurantes": ["restaurante", "cardápio", "reserva", "delivery"],
        "servicos_locais": ["orçamento", "serviço", "atendimento", "região"],
    }
    n = (niche or "odontologia").lower().split("-")[0]
    for key, words in keywords.items():
        if key in n or n in key:
            return any(w in html for w in words)
    return True
