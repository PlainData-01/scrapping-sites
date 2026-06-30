"""Geração do email de prospecção pronto para envio."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from config import SiteData

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_URL_PREFIX = re.compile(r"^\[[^\]]+\]\s*")

_CAT_PRIORIDADE: dict[str, int] = {
    "wix": 0,
    "multiplos_h1": 1,
    "h1_ausente": 2,
    "texto_curto": 3,
    "sem_meta": 4,
    "title_ausente": 5,
    "title_longa": 6,
    "sem_alt": 7,
    "outro": 8,
}


def _limpar_issue(issue: str) -> str:
    """Remove prefixo de URL entre colchetes."""
    return _URL_PREFIX.sub("", issue.strip())


def _formatar_problema_humano(issue: str) -> str:
    """Converte issue técnico de SEO em linguagem natural para o email."""
    text = _limpar_issue(issue).lower()

    if "sem alt text" in text or "sem alt" in text:
        return "imagens sem descrição nas páginas, o que prejudica o SEO"
    if "múltiplos h1" in text:
        return (
            "múltiplos títulos principais em várias páginas de serviço, "
            "confundindo o Google"
        )
    if "title tag muito longa" in text:
        return (
            "títulos de página muito longos, que aparecem cortados "
            "nos resultados do Google"
        )
    if "texto muito curto" in text:
        return (
            "páginas com pouco conteúdo, que o Google considera pouco relevantes"
        )
    if "wix" in text:
        return (
            "site construído no Wix, com limitações técnicas de SEO e performance"
        )
    if "meta description" in text and ("ausência" in text or "ausente" in text):
        return "páginas sem descrição nos resultados de busca do Google"
    if "h1 ausente" in text:
        return "páginas importantes sem título principal, prejudicando o ranqueamento"
    if "title tag ausente" in text:
        return "páginas sem título definido, dificultando a indexação no Google"
    if "squarespace" in text:
        return (
            "site construído no Squarespace, com limitações de personalização e SEO"
        )
    if "duda" in text or "multiscreen" in text:
        return (
            "site construído no Duda, com limitações técnicas de SEO e performance"
        )
    if "wordpress" in text and ("lento" in text or "desatualizado" in text):
        return "site WordPress com problemas de performance ou manutenção"

    # Fallback: remove jargão técnico residual
    fallback = _limpar_issue(issue)
    fallback = re.sub(r"\balt text\b", "descrição", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\bH1s?\b", "títulos principais", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\bTitle tag\b", "título da página", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\bmeta description\b", "descrição da página", fallback, flags=re.IGNORECASE)
    return fallback.lower() if fallback else "há oportunidades de melhoria no site"


def _categoria_issue(issue: str) -> str:
    """Agrupa issues semelhantes para contagem de impacto."""
    text = _limpar_issue(issue).lower()
    if "wix" in text:
        return "wix"
    if "múltiplos h1" in text:
        return "multiplos_h1"
    if "h1 ausente" in text:
        return "h1_ausente"
    if "texto muito curto" in text:
        return "texto_curto"
    if "meta description" in text:
        return "sem_meta"
    if "title tag ausente" in text:
        return "title_ausente"
    if "title tag muito longa" in text:
        return "title_longa"
    if "alt text" in text:
        return "sem_alt"
    return "outro"


def _detectar_wix(site_data: SiteData) -> bool:
    for page in site_data.pages:
        html = (page.get("html") or "").lower()
        url = (page.get("url") or "").lower()
        if any(k in html or k in url for k in ("wix.com", "wixsite", "wixstatic")):
            return True
    return False


def _escolher_problema_principal(
    seo_issues: list[str],
    analysis: dict,
    site_data: SiteData,
) -> str:
    """Seleciona o problema mais impactante e retorna em linguagem humana."""
    platform = (analysis.get("platform") or "").lower()

    if "wix" in platform or _detectar_wix(site_data):
        return _formatar_problema_humano("site construído no wix")

    if not seo_issues:
        problems = analysis.get("current_site_problems", [])
        if problems:
            return _formatar_problema_humano(problems[0])
        return "há oportunidades de melhoria no site"

    contagens: dict[str, int] = {}
    exemplos: dict[str, str] = {}
    for issue in seo_issues:
        cat = _categoria_issue(issue)
        contagens[cat] = contagens.get(cat, 0) + 1
        exemplos.setdefault(cat, issue)

    # Prioridade por volume de ocorrências e tipo de problema
    melhor_cat = max(
        contagens,
        key=lambda c: (contagens[c], -_CAT_PRIORIDADE.get(c, 99)),
    )

    if melhor_cat == "multiplos_h1" and contagens[melhor_cat] < 2:
        outras = [c for c in contagens if c != "multiplos_h1"]
        if outras:
            melhor_cat = max(
                outras,
                key=lambda c: (contagens[c], -_CAT_PRIORIDADE.get(c, 99)),
            )

    return _formatar_problema_humano(exemplos.get(melhor_cat, seo_issues[0]))


def _normalizar_espacos(texto: str) -> str:
    """Remove espaços duplicados e normaliza quebras de linha."""
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _formatar_abertura_email(business_name: str, main_problem: str) -> str:
    """Monta a frase de abertura sem 'que' duplicado."""
    problema = main_problem.strip()
    if problema.startswith(("há ", "existem ")):
        return f"Analisei o site da {business_name} e {problema}"
    return f"Analisei o site da {business_name} e encontrei {problema}"


def generate_prospecting_email(analysis: dict, site_data: SiteData) -> dict:
    """
    Gera conteúdo do email de prospecção.

    Retorna dict com subject, body_text e body_html.
    Não envia o email automaticamente.
    """
    business_name = analysis.get("business_name", site_data.domain)
    main_problem = _escolher_problema_principal(
        site_data.seo_issues or [],
        analysis,
        site_data,
    )
    abertura = _formatar_abertura_email(business_name, main_problem)

    subject = f"{business_name} — oportunidade para melhorar seu site"

    body_text = _normalizar_espacos(
        f"Olá,\n\n"
        f"{abertura}.\n\n"
        f"Trabalho com redesign de sites para negócios como o seu e acredito que "
        f"um site mais moderno e otimizado poderia trazer mais clientes.\n\n"
        f"Preparei uma proposta personalizada com diagnóstico e melhorias sugeridas. "
        f"Posso enviar a proposta completa?\n\n"
        f"Abraço!"
    )

    words = body_text.split()
    if len(words) > 150:
        body_text = " ".join(words[:150])
        if not body_text.endswith("."):
            body_text += "."

    body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
<p>Olá,</p>
<p>{abertura}.</p>
<p>Trabalho com redesign de sites para negócios como o seu e acredito que um site mais moderno e otimizado poderia trazer mais clientes.</p>
<p>Preparei uma proposta personalizada com diagnóstico e melhorias sugeridas. <strong>Posso enviar a proposta completa?</strong></p>
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
