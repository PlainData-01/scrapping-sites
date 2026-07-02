"""Registro simples de atividade comercial por lead."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR
from models.lead_status import normalize_status

logger = logging.getLogger(__name__)

ACTIVITY_FILE = OUTPUT_DIR / "leads" / "activity.json"

CHANNELS = frozenset({"whatsapp", "ligacao", "email", "outro"})
OUTCOMES = frozenset({
    "sem_resposta", "respondeu", "interessado", "sem_interesse",
    "pediu_preco", "chamar_depois", "fechado", "perdido",
})

ACTIVITY_TYPES = frozenset({
    "lead_created", "status_changed", "message_copied", "whatsapp_opened",
    "diagnosis_generated", "prototype_generated", "note_added", "csv_exported",
    "manual", "quick_action",
})


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _garantir() -> None:
    ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)


def _ler() -> dict[str, list[dict]]:
    _garantir()
    if not ACTIVITY_FILE.exists():
        return {}
    try:
        return json.loads(ACTIVITY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _salvar(data: dict[str, list[dict]]) -> None:
    _garantir()
    tmp = ACTIVITY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ACTIVITY_FILE)


def log_event(
    domain: str,
    activity_type: str,
    title: str,
    description: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Registra evento estruturado no histórico do lead."""
    from prospector.leads_crm import normalizar_dominio
    import os

    domain = normalizar_dominio(domain)
    entry: dict[str, Any] = {
        "id": str(uuid.uuid4())[:8],
        "lead_id": domain,
        "type": activity_type if activity_type in ACTIVITY_TYPES else "manual",
        "title": title,
        "description": description,
        "created_at": _agora(),
        "usuario": os.getenv("USUARIO", ""),
        **extra,
    }
    data = _ler()
    data.setdefault(domain, []).append(entry)
    _salvar(data)
    return entry


def registrar_atividade(
    domain: str,
    *,
    status_novo: str = "",
    nota: str = "",
    canal: str = "whatsapp",
    resultado: str = "",
    usuario: str = "",
) -> dict[str, Any]:
    """Registra entrada legada + formato estruturado."""
    from prospector.leads_crm import normalizar_dominio
    import os

    domain = normalizar_dominio(domain)
    canal = canal if canal in CHANNELS else "outro"
    if resultado and resultado not in OUTCOMES:
        resultado = ""

    title = nota.strip() or (f"Status → {status_novo}" if status_novo else "Atividade")
    entry = log_event(
        domain,
        "status_changed" if status_novo else "manual",
        title,
        description=nota,
        status_novo=normalize_status(status_novo) if status_novo else "",
        canal=canal,
        resultado=resultado,
        usuario=usuario or os.getenv("USUARIO", ""),
    )
    return entry


def listar_atividades(domain: str) -> list[dict]:
    from prospector.leads_crm import normalizar_dominio
    items = _ler().get(normalizar_dominio(domain), [])
    return sorted(items, key=lambda x: x.get("created_at", x.get("timestamp", "")), reverse=True)


def acao_rapida(domain: str, acao: str, nota: str = "") -> dict[str, Any]:
    """Mapeia ações rápidas da UI para status + atividade."""
    mapping = {
        "abordado": ("contacted", "sem_resposta", "Abordado pelo WhatsApp"),
        "respondeu": ("responded", "respondeu", "Lead respondeu"),
        "interessado": ("interested", "interessado", "Marcado como interessado"),
        "pediu_preco": ("responded", "pediu_preco", "Pediu preço"),
        "chamar_depois": ("follow_up_later", "chamar_depois", "Chamar depois"),
        "perdido": ("lost", "perdido", "Marcado como perdido"),
        "fechado": ("closed", "fechado", "Fechado"),
        "descartado": ("discarded", "sem_interesse", "Descartado"),
        "prototipo_enviado": ("prototype_sent", "interessado", "Protótipo enviado"),
        "proposta_enviada": ("proposal_sent", "interessado", "Proposta enviada"),
    }
    status, resultado, title = mapping.get(acao, ("", "", acao.replace("_", " ").title()))
    if status:
        from prospector.leads_crm import atualizar_status
        atualizar_status(domain, status)
    return log_event(
        domain,
        "quick_action",
        title,
        description=nota or acao,
        status_novo=status,
        resultado=resultado,
    )
