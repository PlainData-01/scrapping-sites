"""Integração com Claude API para análise consolidada do site."""

from __future__ import annotations

import json
import logging
import re

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, SiteData

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um consultor de marketing digital especializado em redesign de sites.
Analise os dados do site fornecido e retorne SOMENTE um JSON válido com esta estrutura:
{
  "business_name": "nome do negócio detectado",
  "business_type": "tipo de negócio (ex: clínica odontológica, loja de roupas...)",
  "business_description": "descrição em 2 frases do que o negócio faz",
  "target_audience": "público-alvo identificado",
  "current_site_problems": ["problema 1", "problema 2", ...],
  "value_proposition": "proposta de valor do negócio em 1 frase",
  "suggested_improvements": ["melhoria 1", "melhoria 2", ...],
  "proposal_highlights": ["ponto de venda 1", "ponto de venda 2", ...],
  "urgency_points": ["por que o cliente precisa mudar agora..."],
  "estimated_page_count": número de páginas sugeridas para o novo site,

  "niche_category": "uma categoria ampla: saude_premium | industrial_b2b | varejo_local | servicos_profissionais | gastronomia | educacao | imobiliario | tecnologia | outro",

  "design_direction": {
    "tone": "descreva em 1 frase o tom visual certo para ESTE negócio específico — não genérico. Ex: 'robusto e técnico, transmite confiabilidade industrial' vs 'delicado e premium, transmite cuidado pessoal'",
    "visual_risk": "uma escolha de design ousada e específica que faz sentido para este nicho e que NÃO é o default (ex: não sugerir 'fundo creme + serif elegante' para uma empresa industrial)",
    "avoid": "liste 2-3 clichês visuais que esse nicho tende a usar em excesso e que devem ser evitados (ex: para clínicas: 'sorrisos genéricos de banco de imagem, ícone de dente como logo'; para industrial: 'fotos de stock de aperto de mãos, ícones genéricos de engrenagem')",
    "color_mood": "descreva o mood de cor em palavras, não hex ainda (ex: 'aço escuro e âmbar de alerta, como painel industrial' vs 'marfim e bronze, como joalheria')",
    "typography_mood": "descreva o estilo tipográfico em palavras (ex: 'condensada e técnica, como manual de engenharia' vs 'serifada e editorial, como revista de luxo')",
    "signature_element": "sugira UM elemento visual de assinatura específico para este negócio que o tornaria memorável e diferente de qualquer concorrente genérico"
  },

  "competitor_baseline": "com base no tipo de negócio e região, descreva em 1-2 frases como os concorrentes desse nicho tipicamente apresentam seus sites, para que o redesign seja deliberadamente diferente disso"
}

Seja ESPECÍFICO nos campos de design_direction e niche_category — evite respostas genéricas que serviriam para qualquer negócio do mesmo setor.

Para os campos de design_direction, evite sugestões que serviriam para qualquer negócio do mesmo setor genérico. Baseie-se no conteúdo real extraído do site (textos, tom de voz, credenciais, tipo de cliente que atende) para fazer escolhas específicas para ESTE negócio em particular, não para 'clínicas odontológicas' ou 'empresas de energia' em geral.

Não inclua markdown, apenas o JSON puro."""


SYSTEM_PROMPT_PROSPECCAO = """Você é um consultor de marketing digital especializado em prospecção.
Analise os dados do site fornecido e retorne SOMENTE um JSON válido com esta estrutura:
{
  "business_name": "nome do negócio detectado",
  "business_type": "tipo de negócio (ex: clínica odontológica)",
  "current_site_problems": ["problema 1", "problema 2", "problema 3"],
  "urgency_points": ["por que o cliente precisa mudar agora"],
  "niche_category": "saude_premium | industrial_b2b | varejo_local | servicos_profissionais | gastronomia | educacao | imobiliario | tecnologia | outro"
}

Seja específico e baseie-se no conteúdo real extraído. Não inclua markdown, apenas JSON puro."""


def _build_analysis_prompt_prospeccao(site_data: SiteData) -> str:
    """Prompt reduzido para modo prospecção."""
    lines = [
        f"Domínio: {site_data.domain}",
        f"Total de páginas: {len(site_data.pages)}",
        "",
        "=== PROBLEMAS DE SEO ===",
    ]
    for issue in site_data.seo_issues[:10]:
        lines.append(f"- {issue}")
    lines.append("")
    lines.append("=== CONTEÚDO (resumo) ===")
    for page in site_data.pages[:5]:
        lines.append(f"\n--- {page.get('url', '')} ---")
        for section in page.get("sections", [])[:2]:
            text = section.get("text", "")[:300]
            if text:
                lines.append(text)
    return "\n".join(lines)


def _build_analysis_prompt(site_data: SiteData) -> str:
    """Monta prompt consolidado com dados de todas as páginas."""
    lines = [
        f"Domínio: {site_data.domain}",
        f"URL base: {site_data.url}",
        f"Total de páginas: {len(site_data.pages)}",
        "",
        "=== CONTATOS ENCONTRADOS ===",
        json.dumps(site_data.contacts, ensure_ascii=False, indent=2),
        "",
        "=== PROBLEMAS DE SEO ===",
    ]
    for issue in site_data.seo_issues[:20]:
        lines.append(f"- {issue}")

    lines.append("")
    lines.append("=== PÁGINAS E CONTEÚDO ===")
    for page in site_data.pages[:15]:
        lines.append(f"\n--- {page.get('url', '')} (tipo: {page.get('page_type', 'other')}) ---")
        if page.get("seo_issues"):
            lines.append(f"SEO issues: {', '.join(page['seo_issues'][:5])}")
        sections = page.get("sections", [])
        for section in sections[:3]:
            text = section.get("text", "")[:500]
            if text:
                lines.append(text)

    if site_data.colors:
        lines.append(f"\nCores detectadas: {', '.join(site_data.colors[:5])}")
    if site_data.fonts:
        lines.append(f"Fontes detectadas: {', '.join(site_data.fonts[:3])}")

    return "\n".join(lines)


def _parse_json_response(text: str) -> dict:
    """Extrai e parseia JSON da resposta da API."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


async def analyze_site(
    site_data: SiteData,
    modo_prospeccao: bool = False,
) -> dict:
    """
    Analisa o site com uma única chamada consolidada à API Claude.

    modo_prospeccao=True: prompt reduzido, só extrai o essencial
    para gerar mensagem de WhatsApp e qualificar o lead.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY não configurada")
        return _fallback_analysis(site_data, modo_prospeccao=modo_prospeccao)

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    if modo_prospeccao:
        system_prompt = SYSTEM_PROMPT_PROSPECCAO
        prompt = _build_analysis_prompt_prospeccao(site_data)
        max_tokens = 1024
    else:
        system_prompt = SYSTEM_PROMPT
        prompt = _build_analysis_prompt(site_data)
        max_tokens = 4096

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text
        analysis = _parse_json_response(content)
        if modo_prospeccao:
            logger.info(
                "Análise IA (prospecção) concluída para %s — ~%d tokens max",
                site_data.domain, max_tokens,
            )
        else:
            logger.info("Análise IA concluída para %s", site_data.domain)
        return analysis

    except Exception as exc:
        logger.error("Falha na análise com Claude API: %s", exc)
        return _fallback_analysis(site_data, modo_prospeccao=modo_prospeccao)


def _detect_niche_fallback(site_data: SiteData) -> str:
    """Heurística simples de nicho quando a IA não está disponível."""
    text = " ".join(
        (page.get("title") or page.get("meta", {}).get("title", "") or "")
        + " "
        + (page.get("meta_description") or page.get("meta", {}).get("description", "") or "")
        for page in site_data.pages
    ).lower()

    niche_keywords = {
        "saude_premium": ["clínica", "dentista", "odontolog", "médic", "saúde", "estética"],
        "industrial_b2b": ["gerador", "industrial", "engenharia", "manutenção", "energia", "equipamento"],
        "varejo_local": ["loja", "produto", "comprar", "vendas", "moda", "roupa"],
        "servicos_profissionais": ["advogado", "contador", "consultoria", "advocacia"],
        "gastronomia": ["restaurante", "cardápio", "comida", "chef", "gastronomia"],
        "educacao": ["curso", "escola", "ensino", "aula", "educação"],
        "imobiliario": ["imóvel", "imobiliária", "aluguel", "venda de casa", "apartamento"],
    }

    for niche, keywords in niche_keywords.items():
        if any(kw in text for kw in keywords):
            return niche
    return "outro"


def _fallback_analysis(
    site_data: SiteData,
    modo_prospeccao: bool = False,
) -> dict:
    """Análise básica sem IA quando a API falha."""
    base = {
        "business_name": site_data.domain,
        "business_type": "Negócio local",
        "current_site_problems": site_data.seo_issues[:3] or [
            "Site precisa de modernização",
            "Oportunidades de melhoria em SEO",
        ],
        "urgency_points": [
            "Concorrentes já possuem sites modernos",
            "SEO deficiente reduz visibilidade no Google",
        ],
        "niche_category": _detect_niche_fallback(site_data),
    }
    if modo_prospeccao:
        return base

    return {
        **base,
        "business_description": f"Empresa com presença online em {site_data.domain}.",
        "target_audience": "Clientes locais e regionais",
        "value_proposition": "Presença digital para alcançar mais clientes",
        "suggested_improvements": [
            "Redesign responsivo moderno",
            "Otimização para SEO",
            "Melhoria na experiência do usuário",
            "Integração com redes sociais",
        ],
        "proposal_highlights": [
            "Design profissional e responsivo",
            "Otimização para Google",
            "Suporte e manutenção inclusos",
        ],
        "estimated_page_count": max(5, len(site_data.pages)),
    }


def generate_proposal_text(analysis: dict, site_data: SiteData) -> str:
    """
    Gera texto completo da proposta em português brasileiro.

    Máximo 800 palavras, tom profissional e direto.
    """
    business = analysis.get("business_name", site_data.domain)
    problems = analysis.get("current_site_problems", [])
    improvements = analysis.get("suggested_improvements", [])
    highlights = analysis.get("proposal_highlights", [])
    page_count = analysis.get("estimated_page_count", 5)

    problems_text = "\n".join(f"• {p}" for p in problems[:6])
    improvements_text = "\n".join(f"• {i}" for i in improvements[:8])
    highlights_text = "\n".join(f"• {h}" for h in highlights[:5])

    text = f"""PROPOSTA DE REDESIGN DO SITE — {business}

Prezado(a) responsável pela {business},

Após análise detalhada do site {site_data.domain}, identificamos oportunidades significativas para fortalecer a presença digital do seu negócio.

DIAGNÓSTICO DO SITE ATUAL

{analysis.get('business_description', '')}

Analisamos {len(site_data.pages)} páginas e identificamos os seguintes pontos de atenção:

{problems_text}

O QUE VAMOS ENTREGAR

Proposta de redesign completo com foco em conversão e experiência do usuário:

{improvements_text}

Nossos diferenciais:

{highlights_text}

ESCOPO DO PROJETO

• {page_count} páginas otimizadas e responsivas
• Design moderno alinhado à identidade visual do negócio
• Otimização completa para SEO (Google)
• Integração com WhatsApp e redes sociais
• Formulário de contato otimizado
• Certificado SSL e performance otimizada

PRAZO ESTIMADO

• Proposta e briefing: 3 dias úteis
• Design e aprovação: 10 dias úteis
• Desenvolvimento: 15 dias úteis
• Revisões e lançamento: 5 dias úteis
• Prazo total estimado: 30 a 40 dias úteis

PRÓXIMOS PASSOS

1. Agendar reunião de briefing (30 minutos)
2. Aprovação da proposta e contrato
3. Início do projeto com cronograma detalhado

Estamos à disposição para apresentar esta proposta em detalhes e responder suas dúvidas.

Atenciosamente,
Equipe de Desenvolvimento Web
"""

    words = text.split()
    if len(words) > 800:
        text = " ".join(words[:800])

    return text
