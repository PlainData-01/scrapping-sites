"""Geração do email de prospecção pronto para envio."""

from __future__ import annotations

import logging
from pathlib import Path

from config import SiteData

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def generate_prospecting_email(analysis: dict, site_data: SiteData) -> dict:
    """
    Gera conteúdo do email de prospecção.

    Retorna dict com subject, body_text e body_html.
    Não envia o email automaticamente.
    """
    business_name = analysis.get("business_name", site_data.domain)
    problems = analysis.get("current_site_problems", [])
    main_problem = problems[0] if problems else "oportunidades de melhoria no site"

    subject = f"{business_name} — oportunidade para melhorar seu site"

    body_text = (
        f"Olá,\n\n"
        f"Analisei o site da {business_name} e notei que {main_problem.lower()}.\n\n"
        f"Trabalho com redesign de sites para negócios como o seu e acredito que "
        f"um site mais moderno e otimizado poderia trazer mais clientes.\n\n"
        f"Preparei uma proposta personalizada com diagnóstico e melhorias sugeridas. "
        f"Posso enviar a proposta completa?\n\n"
        f"Abraço!"
    )

    words = body_text.split()
    if len(words) > 150:
        body_text = " ".join(words[:150])

    body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
<p>Olá,</p>
<p>Analisei o site da <strong>{business_name}</strong> e notei que {main_problem.lower()}.</p>
<p>Trabalho com redesign de sites para negócios como o seu e acredito que
um site mais moderno e otimizado poderia trazer mais clientes.</p>
<p>Preparei uma proposta personalizada com diagnóstico e melhorias sugeridas.
<strong>Posso enviar a proposta completa?</strong></p>
<p>Abraço!</p>
</body>
</html>"""

    result = {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
    }

    logger.info("Email de prospecção gerado para %s", business_name)
    return result
