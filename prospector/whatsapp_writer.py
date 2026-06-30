"""
Gera mensagens de WhatsApp personalizadas para prospecção.
Usa os dados do scraping (problemas SEO, tipo de negócio, contatos)
para criar mensagens que mencionam um problema ESPECÍFICO do site.
"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse

from config import SiteData

logger = logging.getLogger(__name__)

ABERTURAS = [
    "Vi o site da {nome} e identifiquei",
    "Analisei o site da {nome} e encontrei",
    "Dei uma olhada no site da {nome} e notei",
    "Fiz uma análise rápida do site da {nome} e vi",
]

FECHAMENTOS = [
    "Posso te mostrar como ficaria sem compromisso?",
    "Posso te enviar o diagnóstico completo?",
    "Quer ver o que melhoraria? Não tem compromisso.",
    "Posso mandar uma proposta personalizada?",
]

TEMPLATES: dict[str, dict[str, str]] = {
    "multiplos_h1": {
        "problema": "múltiplos títulos H1 em {n} páginas de serviço",
        "impacto": "isso confunde o Google sobre qual página ranquear para cada tratamento",
    },
    "sem_h1": {
        "problema": "ausência de título principal em páginas importantes",
        "impacto": "as páginas ficam invisíveis nas buscas do Google",
    },
    "texto_curto": {
        "problema": "páginas com pouco conteúdo ({n} palavras em média)",
        "impacto": "o Google não considera essas páginas relevantes o suficiente",
    },
    "sem_meta": {
        "problema": "ausência de descrições nas páginas",
        "impacto": "o site aparece com texto genérico nos resultados de busca",
    },
    "wix": {
        "problema": "site construído no Wix",
        "impacto": "tem limitações técnicas de SEO e performance que impedem crescimento orgânico",
    },
    "wordpress_lento": {
        "problema": "tempo de carregamento elevado",
        "impacto": "mais de 50% dos visitantes abandonam sites que demoram mais de 3 segundos",
    },
    "generico": {
        "problema": "oportunidades de melhoria técnica e de conversão",
        "impacto": "o site atual pode estar deixando clientes escaparem",
    },
    "site_terceirizado": {
        "problema": "presença apenas em plataforma de terceiros (sem site próprio)",
        "impacto": "clientes que buscam no Google encontram o perfil da plataforma, não a clínica diretamente",
    },
}


def _texto_issue(issue: str) -> str:
    """Remove prefixo [url] dos issues consolidados."""
    if "] " in issue:
        return issue.split("] ", 1)[-1].lower()
    return issue.lower()


def _contar_issues(issues: list[str], *patterns: str) -> int:
    return sum(
        1 for i in issues
        if any(p in _texto_issue(i) for p in patterns)
    )


def _escolher_variacoes(domain: str) -> tuple[str, str]:
    """Escolhe abertura e fechamento de forma determinística por domínio."""
    idx = int(hashlib.md5(domain.encode(), usedforsecurity=False).hexdigest(), 16)
    abertura = ABERTURAS[idx % len(ABERTURAS)]
    fechamento = FECHAMENTOS[idx % len(FECHAMENTOS)]
    return abertura, fechamento


def _detect_wix(site_data: SiteData) -> bool:
    for page in site_data.pages:
        html = (page.get("html") or "").lower()
        url = (page.get("url") or "").lower()
        if "wix.com" in html or "wixsite" in html or "wixstatic" in html:
            return True
        if "wix.com" in url:
            return True
    return False


def _escolher_problema_principal(
    site_data: SiteData,
    analysis: dict,
    plataforma_detectada: str = "",
    site_terceirizado: bool = False,
) -> dict:
    """Escolhe o problema mais impactante para mencionar na mensagem."""
    issues = list(site_data.seo_issues or [])
    if not issues:
        issues = list(analysis.get("current_site_problems") or [])

    logger.info(
        "Escolhendo problema para %s: %d issues disponíveis: %s",
        site_data.domain,
        len(issues),
        issues[:3],
    )

    if site_terceirizado:
        return dict(TEMPLATES["site_terceirizado"])

    issues_text = " ".join(_texto_issue(i) for i in issues)
    platform = (analysis.get("platform") or plataforma_detectada or "").lower()

    h1_count = _contar_issues(issues, "múltiplos h1")
    if h1_count >= 2:
        return {**TEMPLATES["multiplos_h1"], "n": str(h1_count)}

    if "wix" in platform or _detect_wix(site_data) or "wix" in issues_text:
        return dict(TEMPLATES["wix"])

    sem_h1 = _contar_issues(issues, "h1 ausente")
    if sem_h1 >= 1:
        return dict(TEMPLATES["sem_h1"])

    texto_curto = _contar_issues(issues, "texto muito curto")
    if texto_curto >= 1:
        palavras = 80
        for issue in issues:
            match = re.search(r"(\d+)\s*palavras", _texto_issue(issue))
            if match:
                palavras = int(match.group(1))
                break
        return {**TEMPLATES["texto_curto"], "n": str(palavras)}

    sem_meta = _contar_issues(issues, "meta description")
    if sem_meta >= 1:
        return dict(TEMPLATES["sem_meta"])

    if platform in ("squarespace", "hostinger", "duda"):
        return {
            "problema": f"site construído no {platform.title()}",
            "impacto": TEMPLATES["wix"]["impacto"],
        }

    return dict(TEMPLATES["generico"])


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


def _normalize_whatsapp(numero: str) -> str:
    return _limpar_telefone(numero)


def _montar_whatsapp_link(tel: str, mensagem: str = "") -> str:
    numero = _limpar_telefone(tel)
    if not numero:
        return ""
    if mensagem:
        return f"https://wa.me/{numero}?text={urllib.parse.quote(mensagem)}"
    return f"https://wa.me/{numero}"


def _build_whatsapp_link(numero: str, mensagem: str) -> str:
    return _montar_whatsapp_link(numero, mensagem)


def gerar_mensagem_whatsapp(
    site_data: SiteData,
    analysis: dict,
    tem_prototipo: bool = False,
    telefone_fallback: str = "",
    plataforma_detectada: str = "",
    site_terceirizado: bool = False,
) -> dict:
    """
    Gera mensagem de WhatsApp personalizada para prospecção.

    Returns:
        dict com mensagem_curta, mensagem_completa, whatsapp_link, etc.
    """
    business_name = analysis.get("business_name") or site_data.domain
    whatsapp = site_data.contacts.get("whatsapp", "") or telefone_fallback
    whatsapp = _limpar_telefone(whatsapp) or whatsapp

    problema = _escolher_problema_principal(
        site_data, analysis, plataforma_detectada, site_terceirizado,
    )
    problema_texto = problema["problema"].format(n=problema.get("n", ""))
    impacto_texto = problema["impacto"]
    abertura_tpl, fechamento = _escolher_variacoes(site_data.domain)
    abertura = abertura_tpl.format(nome=business_name)

    if tem_prototipo:
        gancho = (
            "Preparei um protótipo do novo site para ver como ficaria — "
            "posso te mostrar sem nenhum compromisso?"
        )
    else:
        gancho = fechamento

    mensagem_curta = (
        f"Olá! {abertura} {problema_texto}. "
        f"{impacto_texto.capitalize()}. "
        f"{gancho}"
    )

    mensagem_completa = (
        f"Olá! Tudo bem?\n\n"
        f"{abertura} {problema_texto}, "
        f"o que significa que {impacto_texto}.\n\n"
        f"{gancho}\n\n"
        f"Abraço!"
    )

    whatsapp_link = _build_whatsapp_link(whatsapp, mensagem_curta)
    followup = gerar_mensagem_followup(business_name, whatsapp)

    return {
        "mensagem_curta": mensagem_curta,
        "mensagem_completa": mensagem_completa,
        "whatsapp_link": whatsapp_link,
        "whatsapp_followup_link": followup.get("whatsapp_link", ""),
        "mensagem_followup": followup.get("mensagem", ""),
        "problema_detectado": problema_texto,
        "business_name": business_name,
        "whatsapp_numero": whatsapp,
    }


def gerar_mensagem_followup(business_name: str, whatsapp: str = "") -> dict:
    """Gera mensagem de follow-up quando o cliente responde SIM."""
    mensagem = (
        f"Ótimo! Já tenho aqui um protótipo do novo site da {business_name}. "
        f"Vou te mandar o link agora para você ver como ficaria."
    )
    link = _montar_whatsapp_link(whatsapp, mensagem) if whatsapp else ""
    return {"mensagem": mensagem, "whatsapp_numero": whatsapp, "whatsapp_link": link}
