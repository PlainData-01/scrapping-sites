"""Persistência de status e notas dos leads para o hub CRM."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from config import OUTPUT_DIR

from models.lead_status import VALID_STATUSES, normalize_status

logger = logging.getLogger(__name__)

LEADS_DIR = OUTPUT_DIR / "leads"
STATUS_FILE = LEADS_DIR / "status.json"
NOTAS_FILE = LEADS_DIR / "notas.json"
UI_CONFIG_FILE = LEADS_DIR / "ui_config.json"

# Status válidos (novo modelo + legado)
STATUS_VALIDOS = VALID_STATUSES | frozenset({
    "pendente", "abordado", "interessado", "fechado", "perdido", "descartado", "pronto",
})

DEFAULT_UI_CONFIG = {
    "delay_entre_leads": 5,
    "timeout_lead": 180,
    "paginas_por_lead": 8,
    "cache_dias": 7,
    "icp_id": "odontologia",
    "regioes_premium": [
        "asa sul", "asa norte", "lago sul", "lago norte",
        "sudoeste", "noroeste", "águas claras", "park sul",
    ],
}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _garantir_pasta() -> None:
    LEADS_DIR.mkdir(parents=True, exist_ok=True)


def _ler_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _salvar_json(path: Path, data: dict[str, Any]) -> None:
    _garantir_pasta()
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def normalizar_dominio(domain_or_url: str) -> str:
    """Extrai domínio limpo de URL ou slug."""
    d = domain_or_url.strip().lower()
    if d.startswith("http"):
        d = urlparse(d).netloc
    d = d.replace("www.", "").replace("_", ".")
    return d


def ler_status_todos() -> dict[str, Any]:
    return _ler_json(STATUS_FILE)


def ler_notas_todos() -> dict[str, list[str]]:
    return _ler_json(NOTAS_FILE)


def obter_status(domain: str) -> dict[str, Any]:
    domain = normalizar_dominio(domain)
    return ler_status_todos().get(domain, {"status": "pendente"})


def atualizar_status(domain: str, status: str) -> dict[str, Any]:
    domain = normalizar_dominio(domain)
    normalized = normalize_status(status)
    if status not in STATUS_VALIDOS and normalized not in VALID_STATUSES:
        raise ValueError(f"Status inválido: {status}")

    dados = ler_status_todos()
    entry = dados.get(domain, {})
    entry["status"] = normalized
    entry["updated_at"] = _agora()
    if normalized in ("contacted", "abordado") and "abordado_em" not in entry:
        entry["abordado_em"] = _agora()
    if normalized in ("interested", "interessado"):
        entry["interessado_em"] = _agora()
    if normalized in ("closed", "fechado"):
        entry["fechado_em"] = _agora()
    dados[domain] = entry
    _salvar_json(STATUS_FILE, dados)
    return entry


def adicionar_nota(domain: str, nota: str) -> list[str]:
    domain = normalizar_dominio(domain)
    nota = nota.strip()
    if not nota:
        return ler_notas_todos().get(domain, [])

    dados = ler_notas_todos()
    lista = dados.get(domain, [])
    lista.append({"texto": nota, "criado_em": _agora()})
    dados[domain] = lista
    _salvar_json(NOTAS_FILE, dados)
    return lista


def ler_ui_config() -> dict[str, Any]:
    cfg = {**DEFAULT_UI_CONFIG, **_ler_json(UI_CONFIG_FILE)}
    return cfg


def salvar_ui_config(config: dict[str, Any]) -> dict[str, Any]:
    atual = ler_ui_config()
    for key in DEFAULT_UI_CONFIG:
        if key in config:
            atual[key] = config[key]
    _salvar_json(UI_CONFIG_FILE, atual)
    return atual


def calcular_metricas(leads: list[dict], statuses: dict) -> dict[str, Any]:
    """Calcula métricas do dashboard a partir dos leads e status."""
    hoje = datetime.now(timezone.utc).date().isoformat()
    semana_inicio = datetime.now(timezone.utc).date().isoformat()

    total = len(leads)
    abordados = interessados = fechados = perdidos = 0
    abordados_hoje = 0
    interessados_semana = 0
    alertas_whatsapp = []

    for lead in leads:
        domain = normalizar_dominio(lead.get("website", lead.get("nome", "")))
        raw_st = statuses.get(domain, {}).get("status", lead.get("status_crm", lead.get("crm_status", "new")))
        st = normalize_status(raw_st)
        if st in ("new", "qualified", "pendente", "pronto"):
            pass  # novos / pendentes
        elif st in ("contacted", "abordado"):
            abordados += 1
            abordado_em = statuses.get(domain, {}).get("abordado_em", "")
            if abordado_em.startswith(hoje):
                abordados_hoje += 1
            if abordado_em:
                try:
                    dt = datetime.fromisoformat(abordado_em.replace("Z", "+00:00"))
                    diff = datetime.now(timezone.utc) - dt
                    if diff.total_seconds() > 86400:
                        alertas_whatsapp.append({
                            "nome": lead.get("nome", domain),
                            "domain": domain,
                            "horas": int(diff.total_seconds() / 3600),
                        })
                except ValueError:
                    pass
        elif st in ("interested", "interessado", "prototype_requested", "prototype_sent", "proposal_sent"):
            interessados += 1
            interessados_semana += 1
        elif st in ("closed", "fechado"):
            fechados += 1
        elif st in ("lost", "perdido", "discarded", "descartado"):
            perdidos += 1

    taxa = round((interessados / abordados * 100), 1) if abordados else 0

    return {
        "leads_total": total,
        "leads_hoje": sum(
            1 for l in leads
            if l.get("processado_em", "").startswith(hoje)
        ),
        "abordados_total": abordados,
        "abordados_hoje": abordados_hoje,
        "interessados_semana": interessados_semana,
        "interessados_total": interessados,
        "fechados_total": fechados,
        "taxa_conversao": taxa,
        "alertas_whatsapp": alertas_whatsapp,
    }
