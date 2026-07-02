"""Status comercial dos leads no Prospect Hub."""

from __future__ import annotations

from enum import Enum


class LeadStatus(str, Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    DISCARDED = "discarded"
    CONTACTED = "contacted"
    RESPONDED = "responded"
    INTERESTED = "interested"
    PROTOTYPE_REQUESTED = "prototype_requested"
    PROTOTYPE_SENT = "prototype_sent"
    PROPOSAL_SENT = "proposal_sent"
    CLOSED = "closed"
    LOST = "lost"
    FOLLOW_UP_LATER = "follow_up_later"


STATUS_LABELS_PT: dict[LeadStatus, str] = {
    LeadStatus.NEW: "Novo",
    LeadStatus.QUALIFIED: "Qualificado",
    LeadStatus.DISCARDED: "Descartado",
    LeadStatus.CONTACTED: "Abordado",
    LeadStatus.RESPONDED: "Respondeu",
    LeadStatus.INTERESTED: "Interessado",
    LeadStatus.PROTOTYPE_REQUESTED: "Protótipo solicitado",
    LeadStatus.PROTOTYPE_SENT: "Protótipo enviado",
    LeadStatus.PROPOSAL_SENT: "Proposta enviada",
    LeadStatus.CLOSED: "Fechado",
    LeadStatus.LOST: "Perdido",
    LeadStatus.FOLLOW_UP_LATER: "Chamar depois",
}

# Mapeamento de status legados do CRM v1
LEGACY_STATUS_MAP: dict[str, LeadStatus] = {
    "pendente": LeadStatus.NEW,
    "pronto": LeadStatus.QUALIFIED,
    "abordado": LeadStatus.CONTACTED,
    "interessado": LeadStatus.INTERESTED,
    "fechado": LeadStatus.CLOSED,
    "perdido": LeadStatus.LOST,
    "descartado": LeadStatus.DISCARDED,
}

VALID_STATUSES = frozenset(s.value for s in LeadStatus)


def normalize_status(status: str) -> str:
    """Converte status legado para o enum novo; retorna valor válido ou 'new'."""
    if not status:
        return LeadStatus.NEW.value
    s = status.strip().lower()
    if s in VALID_STATUSES:
        return s
    mapped = LEGACY_STATUS_MAP.get(s)
    if mapped:
        return mapped.value
    return LeadStatus.NEW.value


def status_label_pt(status: str) -> str:
    """Rótulo em português para exibição na UI."""
    normalized = normalize_status(status)
    try:
        return STATUS_LABELS_PT[LeadStatus(normalized)]
    except ValueError:
        return status
