"""Blocos operacionais do dashboard v3.1."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.lead_status import normalize_status
from prospector.next_best_action import build_action_queue, get_next_best_action


def _status(lead: dict) -> str:
    return normalize_status(lead.get("crm_status") or lead.get("status_crm") or "new")


def _score(lead: dict) -> int:
    return int(lead.get("opportunity_score") or lead.get("score") or 0)


def _hoje() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_operational_dashboard(leads: list[dict], metricas: dict) -> dict[str, Any]:
    """Monta blocos acionáveis para o dashboard."""
    novos = [l for l in leads if _status(l) in ("new", "qualified")]
    abordados = [l for l in leads if _status(l) == "contacted"]
    interessados = [l for l in leads if _status(l) in ("interested", "prototype_requested")]
    prototipos_enviados = [l for l in leads if _status(l) == "prototype_sent"]
    fechados = [l for l in leads if _status(l) == "closed"]

    top_score = sorted(leads, key=_score, reverse=True)[:8]

    blocos = {
        "novos_para_revisar": _summarize(novos[:10], "Revisar mensagem e abordar"),
        "maior_score": _summarize(top_score, "Prioridade por oportunidade"),
        "abordados_aguardando": _summarize(abordados[:10], "Aguardando resposta — considere follow-up"),
        "interessados_pendentes": _summarize(interessados[:10], "Gerar diagnóstico ou protótipo"),
        "prototipos_followup": _summarize(prototipos_enviados[:10], "Fazer follow-up"),
        "fechados_periodo": _summarize(fechados[:5], "Fechado"),
    }

    return {
        "metricas": {
            **metricas,
            "novos_total": len(novos),
            "abordados_aguardando": len(abordados),
            "interessados_pendentes": len(interessados),
            "prototipos_enviados": len(prototipos_enviados),
            "prototipos_gerados": _count_prototypes(leads),
        },
        "blocos": blocos,
        "proximas_acoes": build_action_queue(leads, limit=15),
    }


def _summarize(leads: list[dict], acao_padrao: str) -> list[dict]:
    out = []
    for l in leads:
        nba = get_next_best_action(l)
        out.append({
            "domain": l.get("domain", ""),
            "nome": l.get("nome", l.get("domain", "")),
            "score": _score(l),
            "status": _status(l),
            "main_pain": l.get("main_pain") or l.get("problema_principal", ""),
            "acao_sugerida": nba.get("title", acao_padrao),
            "icp_id": l.get("icp_id", ""),
        })
    return out


def _count_prototypes(leads: list[dict]) -> int:
    from config import OUTPUT_DIR
    count = 0
    for l in leads:
        dom = (l.get("domain") or "").replace(".", "_")
        if (OUTPUT_DIR / "sites" / dom / "prototype" / "index.html").exists():
            count += 1
    return count
