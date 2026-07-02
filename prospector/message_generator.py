"""Gerador de mensagens WhatsApp comerciais para prospecção manual."""

from __future__ import annotations

import urllib.parse
from typing import Any

from prospector.whatsapp_writer import _limpar_telefone, gerar_mensagem_whatsapp
from config import SiteData


def _wa_link(telefone: str, mensagem: str) -> str:
    numero = _limpar_telefone(telefone)
    if not numero:
        return ""
    return f"https://wa.me/{numero}?text={urllib.parse.quote(mensagem)}"


def gerar_pacote_mensagens(
    lead: dict[str, Any],
    site_data: SiteData | None = None,
    analysis: dict | None = None,
) -> dict[str, Any]:
    """
    Gera pacote completo de mensagens para o vendedor.

    Retorna: curta, consultiva, follow-ups, respostas a objeções e links wa.me.
    """
    nome = lead.get("business_name") or lead.get("nome", "sua empresa")
    nicho = lead.get("niche") or lead.get("categoria", "")
    cidade = lead.get("city") or _extrair_cidade(lead.get("endereco", ""))
    bairro = lead.get("neighborhood") or ""
    local = f"{bairro}, {cidade}".strip(", ") if bairro else cidade
    avaliacao = float(lead.get("avaliacao") or lead.get("rating") or 0)
    reviews = int(lead.get("total_avaliacoes") or lead.get("reviews_count") or 0)
    dor = lead.get("main_pain") or lead.get("problema_principal", "")
    angulo = lead.get("commercial_angle", "")
    oferta = lead.get("suggested_offer", "")
    telefone = lead.get("whatsapp") or lead.get("telefone", "")

    # Base via whatsapp_writer se temos site_data
    base_msg: dict[str, Any] = {}
    if site_data and analysis:
        base_msg = gerar_mensagem_whatsapp(
            site_data=site_data,
            analysis=analysis,
            telefone_fallback=telefone,
            plataforma_detectada=lead.get("plataforma_detectada", ""),
        )

    curta = base_msg.get("mensagem_curta") or _mensagem_curta(
        nome, dor, avaliacao, reviews, local,
    )
    consultiva = _mensagem_consultiva(nome, dor, angulo, avaliacao, reviews, local, oferta)
    followup1 = _followup_1(nome)
    followup2 = _followup_2(nome)
    resposta_preco = _resposta_preco(nome, oferta)
    resposta_fornecedor = _resposta_fornecedor(nome)
    resposta_interesse = _resposta_interesse(nome, oferta)

    return {
        "mensagem_curta": curta,
        "mensagem_consultiva": consultiva,
        "followup_1": followup1,
        "followup_2": followup2,
        "resposta_preco": resposta_preco,
        "resposta_fornecedor": resposta_fornecedor,
        "resposta_interesse": resposta_interesse,
        "whatsapp_link_curta": _wa_link(telefone, curta),
        "whatsapp_link_consultiva": _wa_link(telefone, consultiva),
        "whatsapp_numero": _limpar_telefone(telefone) or telefone,
        "nicho": nicho,
    }


def _extrair_cidade(endereco: str) -> str:
    if not endereco:
        return ""
    partes = [p.strip() for p in endereco.split(",")]
    return partes[-2] if len(partes) >= 2 else partes[0]


def _mensagem_curta(
    nome: str, dor: str, avaliacao: float, reviews: int, local: str,
) -> str:
    rep = ""
    if reviews >= 20 and avaliacao >= 4.0:
        rep = f" Como vocês já têm boas avaliações no Google ({avaliacao:.1f}★),"
    dor_txt = dor or "alguns pontos simples que podem estar dificultando contatos pelo celular"
    return (
        f"Oi, tudo bem? Vi o site da {nome} e percebi que {dor_txt.lower().rstrip('.')}.{rep} "
        f"acredito que dá para transformar melhor esse tráfego em conversas no WhatsApp.\n\n"
        f"Posso te mandar uma sugestão visual rápida, sem compromisso?"
    )


def _mensagem_consultiva(
    nome: str, dor: str, angulo: str, avaliacao: float,
    reviews: int, local: str, oferta: str,
) -> str:
    linhas = [
        f"Olá! Tudo bem?",
        "",
        f"Analisei o site da {nome}" + (f" ({local})" if local else "") + ".",
    ]
    if dor:
        linhas.append(f"O principal ponto que notei: {dor}")
    if reviews >= 10:
        linhas.append(
            f"Vocês têm {reviews} avaliações com média de {avaliacao:.1f}★ — "
            "isso mostra que já existe demanda."
        )
    if angulo:
        linhas.append(angulo)
    if oferta:
        linhas.append(f"A ideia seria uma {oferta.lower()}.")
    linhas.extend([
        "",
        "Posso preparar uma sugestão visual rápida para você avaliar, sem compromisso?",
    ])
    return "\n".join(linhas)


def _followup_1(nome: str) -> str:
    return (
        f"Oi! Passando para ver se chegou a ver minha mensagem sobre o site da {nome}. "
        f"Se fizer sentido, posso mandar uma sugestão visual rápida — leva só alguns minutos para você avaliar."
    )


def _followup_2(nome: str) -> str:
    return (
        f"Última mensagem por aqui 😊 Vi oportunidade real de melhorar a conversão do site da {nome}. "
        f"Se não for o momento, sem problema — fico à disposição."
    )


def _resposta_preco(nome: str, oferta: str) -> str:
    return (
        f"Boa pergunta! O valor depende do escopo — para a {nome}, "
        f"começo com um diagnóstico e uma sugestão visual ({oferta or 'landing page'}). "
        f"Assim você vê o resultado antes de decidir. Posso te mandar o diagnóstico primeiro?"
    )


def _resposta_fornecedor(nome: str) -> str:
    return (
        f"Entendo perfeitamente! Muitas clínicas/empresas como a {nome} já têm alguém cuidando do site. "
        f"Minha proposta é só mostrar uma sugestão visual com foco em WhatsApp/conversão — "
        f"sem compromisso. Se fizer sentido, ótimo; se não, fica o diagnóstico."
    )


def _resposta_interesse(nome: str, oferta: str) -> str:
    return (
        f"Que ótimo! Vou preparar o mini diagnóstico e uma sugestão visual para a {nome}. "
        f"A ideia é uma {oferta or 'landing page'} focada em gerar contatos pelo WhatsApp. "
        f"Te mando em breve para você avaliar!"
    )
