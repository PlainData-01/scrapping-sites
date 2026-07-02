"""Gerador de mini diagnóstico comercial por lead."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR
from prospector.icp_loader import load_icp


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def generate_diagnosis(
    lead: dict[str, Any],
    *,
    icp_id: str | None = None,
    commercial_analysis: dict | None = None,
    messages: dict | None = None,
) -> dict[str, Any]:
    """
    Gera mini diagnóstico em múltiplos formatos.

    Returns dict com keys: markdown, html, json, paths (se salvos).
    """
    icp = load_icp(icp_id or lead.get("icp_id"))
    nome = lead.get("business_name") or lead.get("nome", "Lead")
    site = lead.get("website_url") or lead.get("website", "")
    nicho = lead.get("niche") or lead.get("categoria") or icp.name
    cidade = lead.get("city") or ""
    bairro = lead.get("neighborhood") or ""
    local = ", ".join(p for p in [bairro, cidade] if p) or lead.get("endereco", "")

    score = int(lead.get("opportunity_score") or lead.get("score") or 0)
    reasons = lead.get("score_reasons") or []
    if isinstance(reasons, str):
        try:
            reasons = json.loads(reasons)
        except json.JSONDecodeError:
            reasons = [reasons]

    issues = []
    if commercial_analysis:
        issues = commercial_analysis.get("commercial_issues") or []
    if not issues:
        issues = reasons[:3]

    recommendations = []
    if commercial_analysis:
        recommendations = commercial_analysis.get("recommendations") or []
    if not recommendations:
        recommendations = [
            "Criar landing page mais direta com CTA para WhatsApp.",
            "Destacar serviços/procedimentos principais.",
            "Incluir prova social e avaliações do Google.",
        ]

    main_pain = lead.get("main_pain") or lead.get("problema_principal", "")
    resumo = main_pain or (reasons[0] if reasons else "Oportunidade de melhorar conversão no site.")

    msg_curta = ""
    if messages:
        msg_curta = messages.get("mensagem_curta", "")
    elif lead.get("mensagem_whatsapp"):
        msg_curta = lead["mensagem_whatsapp"]

    prototype = icp.recommended_prototype
    proximo = "Enviar sugestão visual (protótipo) e agendar conversa rápida."

    structured = {
        "lead_name": nome,
        "website": site,
        "niche": nicho,
        "location": local,
        "summary": resumo,
        "opportunity_score": score,
        "score_reasons": reasons,
        "top_issues": issues[:3],
        "commercial_impact": _impacto_comercial(main_pain),
        "recommendations": recommendations[:3],
        "suggested_message": msg_curta,
        "recommended_prototype": prototype,
        "next_step": proximo,
        "icp_id": icp.id,
        "generated_at": _agora(),
    }

    markdown = _to_markdown(structured)
    html = _to_html(structured)

    return {
        "markdown": markdown,
        "html": html,
        "json": structured,
        "paths": {},
    }


def save_diagnosis(lead: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, str]:
    """Salva diagnóstico em output/diagnoses/{domain}/."""
    domain = lead.get("domain") or lead.get("website", "lead").replace("https://", "").split("/")[0]
    domain = domain.replace("www.", "").replace(".", "_")
    out_dir = OUTPUT_DIR / "diagnoses" / domain
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {}
    md_path = out_dir / "diagnostico.md"
    md_path.write_text(diagnosis["markdown"], encoding="utf-8")
    paths["markdown"] = str(md_path)

    html_path = out_dir / "diagnostico.html"
    html_path.write_text(diagnosis["html"], encoding="utf-8")
    paths["html"] = str(html_path)

    json_path = out_dir / "diagnostico.json"
    json_path.write_text(
        json.dumps(diagnosis["json"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["json"] = str(json_path)

    diagnosis["paths"] = paths
    return paths


def _impacto_comercial(main_pain: str) -> str:
    if "whatsapp" in main_pain.lower() or "cta" in main_pain.lower():
        return (
            "Visitantes interessados podem sair do site sem iniciar contato, "
            "principalmente no celular."
        )
    return (
        "O site pode não transmitir confiança ou clareza suficiente para "
        "converter buscas em contatos qualificados."
    )


def _to_markdown(d: dict[str, Any]) -> str:
    issues = "\n".join(f"{i+1}. {x}" for i, x in enumerate(d["top_issues"]))
    recs = "\n".join(f"{i+1}. {x}" for i, x in enumerate(d["recommendations"]))
    reasons = "\n".join(f"- {r}" for r in (d.get("score_reasons") or [])[:5])

    return f"""# Mini diagnóstico — {d["lead_name"]}

**Site:** {d["website"]}  
**Nicho:** {d["niche"]}  
**Local:** {d["location"]}  
**Score de oportunidade:** {d["opportunity_score"]}/100

## Resumo
{d["summary"]}

## Motivos do score
{reasons or "_Sem detalhes adicionais._"}

## Pontos encontrados
{issues or "_Análise pendente._"}

## Impacto provável
{d["commercial_impact"]}

## Recomendações
{recs}

## Mensagem sugerida de abordagem
{d["suggested_message"] or "_Gerar mensagens na aba do lead._"}

## Protótipo recomendado
`{d["recommended_prototype"]}`

## Próximo passo
{d["next_step"]}

---
_Gerado em {d["generated_at"]} — Prospect Hub_
"""


def _to_html(d: dict[str, Any]) -> str:
    issues = "".join(f"<li>{x}</li>" for x in d["top_issues"])
    recs = "".join(f"<li>{x}</li>" for x in d["recommendations"])
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Mini diagnóstico — {d["lead_name"]}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; color: #1a1a1a; }}
    h1 {{ font-size: 1.5rem; }}
    h2 {{ font-size: 1.1rem; margin-top: 1.5rem; color: #333; }}
    .score {{ background: #f0f4ff; padding: 0.5rem 1rem; border-radius: 8px; display: inline-block; }}
    .msg {{ background: #f9f9f9; padding: 1rem; border-left: 3px solid #2563eb; }}
  </style>
</head>
<body>
  <h1>Mini diagnóstico — {d["lead_name"]}</h1>
  <p><strong>Site:</strong> {d["website"]}<br>
  <strong>Nicho:</strong> {d["niche"]}<br>
  <strong>Local:</strong> {d["location"]}</p>
  <p class="score"><strong>Score:</strong> {d["opportunity_score"]}/100</p>
  <h2>Resumo</h2>
  <p>{d["summary"]}</p>
  <h2>Pontos encontrados</h2>
  <ul>{issues}</ul>
  <h2>Impacto provável</h2>
  <p>{d["commercial_impact"]}</p>
  <h2>Recomendações</h2>
  <ul>{recs}</ul>
  <h2>Mensagem sugerida</h2>
  <div class="msg">{d["suggested_message"] or "—"}</div>
  <h2>Protótipo recomendado</h2>
  <p><code>{d["recommended_prototype"]}</code></p>
  <h2>Próximo passo</h2>
  <p>{d["next_step"]}</p>
  <hr><small>Gerado em {d["generated_at"]} — Prospect Hub</small>
</body>
</html>"""
