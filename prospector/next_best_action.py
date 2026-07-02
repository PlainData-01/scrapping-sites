"""Sugestão da próxima melhor ação comercial por lead."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from models.lead_status import normalize_status


@dataclass
class NextBestAction:
    title: str
    description: str
    primary_action_label: str
    primary_action_type: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


_ACTIONS: dict[str, NextBestAction] = {
    "new": NextBestAction(
        title="Abordar pelo WhatsApp",
        description="Revise a mensagem curta, copie e marque como abordado após enviar.",
        primary_action_label="Copiar mensagem e abordar",
        primary_action_type="copy_and_approach",
    ),
    "qualified": NextBestAction(
        title="Abordar com mensagem consultiva",
        description="Lead qualificado. Use a mensagem consultiva e destaque a dor principal.",
        primary_action_label="Copiar mensagem e abordar",
        primary_action_type="copy_and_approach_consultive",
    ),
    "contacted": NextBestAction(
        title="Aguardar ou fazer follow-up",
        description="Lead já abordado. Envie follow-up 1 ou marque como respondeu quando houver retorno.",
        primary_action_label="Enviar follow-up",
        primary_action_type="copy_followup_1",
    ),
    "responded": NextBestAction(
        title="Classificar interesse",
        description="O lead respondeu. Marque como interessado ou use mensagens de resposta abaixo.",
        primary_action_label="Marcar como interessado",
        primary_action_type="mark_interested",
    ),
    "interested": NextBestAction(
        title="Gerar diagnóstico ou protótipo",
        description="Lead demonstrou interesse. Comece pelo mini diagnóstico para argumentos comerciais.",
        primary_action_label="Gerar diagnóstico",
        primary_action_type="generate_diagnosis",
    ),
    "prototype_requested": NextBestAction(
        title="Gerar protótipo personalizado",
        description="O lead pediu para ver uma sugestão visual. Gere o protótipo com o template do ICP.",
        primary_action_label="Gerar protótipo",
        primary_action_type="generate_prototype",
    ),
    "prototype_sent": NextBestAction(
        title="Fazer follow-up",
        description="Protótipo já enviado. Pergunte se faz sentido avançar ou marque proposta enviada.",
        primary_action_label="Marcar proposta enviada",
        primary_action_type="mark_proposal_sent",
    ),
    "proposal_sent": NextBestAction(
        title="Acompanhar decisão",
        description="Proposta enviada. Registre notas e marque fechado ou perdido conforme o resultado.",
        primary_action_label="Marcar como fechado",
        primary_action_type="mark_closed",
    ),
    "closed": NextBestAction(
        title="Registrar fechamento",
        description="Lead fechado. Registre detalhes do serviço e próximos passos operacionais.",
        primary_action_label="Adicionar nota",
        primary_action_type="add_note",
    ),
    "lost": NextBestAction(
        title="Registrar motivo da perda",
        description="Lead perdido. Anote o motivo para refinar ICP e abordagem futura.",
        primary_action_label="Adicionar nota",
        primary_action_type="add_note",
    ),
    "discarded": NextBestAction(
        title="Lead descartado",
        description="Este lead foi descartado. Nenhuma ação necessária, salvo revisão futura.",
        primary_action_label="Reabrir lead",
        primary_action_type="set_status_new",
    ),
    "follow_up_later": NextBestAction(
        title="Retomar contato",
        description="Lead marcado para retomada. Copie uma mensagem curta e registre o novo contato.",
        primary_action_label="Retomar contato",
        primary_action_type="copy_short_message",
    ),
}


def get_next_best_action(lead: dict[str, Any]) -> dict[str, str]:
    """Retorna próxima melhor ação baseada no status CRM do lead."""
    status = normalize_status(
        lead.get("crm_status") or lead.get("status_crm") or lead.get("status") or "new",
    )
    action = _ACTIONS.get(status, _ACTIONS["new"])

    # Ajustes contextuais
    if status in ("new", "qualified") and not (lead.get("whatsapp") or lead.get("telefone")):
        return NextBestAction(
            title="Verificar contato",
            description="Sem WhatsApp ou telefone claro. Abra o site ou Google Maps para encontrar contato antes de abordar.",
            primary_action_label="Abrir site",
            primary_action_type="open_site",
        ).to_dict()

    if status == "interested" and _has_diagnosis(lead) and not _has_prototype(lead):
        return NextBestAction(
            title="Gerar protótipo",
            description="Diagnóstico pronto. Gere a landing de protótipo para enviar ao lead.",
            primary_action_label="Gerar protótipo",
            primary_action_type="generate_prototype",
        ).to_dict()

    return action.to_dict()


def _has_diagnosis(lead: dict) -> bool:
    from config import OUTPUT_DIR
    domain = (lead.get("domain") or "").replace(".", "_")
    return (OUTPUT_DIR / "diagnoses" / domain / "diagnostico.md").exists()


def _has_prototype(lead: dict) -> bool:
    from config import OUTPUT_DIR
    domain = (lead.get("domain") or "").replace(".", "_")
    return (OUTPUT_DIR / "sites" / domain / "prototype" / "index.html").exists()


def build_action_queue(leads: list[dict], limit: int = 12) -> list[dict[str, Any]]:
    """Monta fila de próximas ações para o dashboard."""
    queue: list[dict[str, Any]] = []
    for lead in leads:
        nba = get_next_best_action(lead)
        status = normalize_status(lead.get("crm_status") or "new")
        queue.append({
            "domain": lead.get("domain", ""),
            "nome": lead.get("nome", lead.get("domain", "")),
            "status": status,
            "score": lead.get("score") or lead.get("opportunity_score") or 0,
            "action_title": nba["title"],
            "action_description": nba["description"],
            "primary_action_type": nba["primary_action_type"],
        })
    # Prioriza: interessados > novos com score alto > abordados aguardando
    priority = {
        "interested": 0, "prototype_requested": 1, "prototype_sent": 2,
        "responded": 3, "new": 4, "qualified": 5, "contacted": 6,
    }
    queue.sort(key=lambda x: (priority.get(x["status"], 9), -int(x["score"] or 0)))
    return queue[:limit]
