"""Servidor web local para operar o scraping agent via interface visual."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)

AGENT_VERSION = "3.2"

app = FastAPI(title="Scraping Agent", docs_url="/docs")

_prospect_task: asyncio.Task | None = None


def _on_prospect_task_done(task: asyncio.Task) -> None:
    """Evita exceções não tratadas na task derrubarem o servidor."""
    if task.cancelled():
        logger.warning("Task de prospecção cancelada — servidor continua rodando")
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Erro na prospecção (task): %s", exc)


async def _run_prospect_task(
    query: str, cidade: str, max_leads: int, icp_id: str | None = None,
) -> None:
    from prospector.pipeline import executar_prospeccao

    try:
        await executar_prospeccao(
            query=query,
            cidade=cidade,
            max_leads=max_leads,
            icp_id=icp_id,
        )
    except asyncio.CancelledError:
        logger.warning("Task de prospecção cancelada — servidor continua rodando")
    except Exception as exc:
        logger.exception("Erro na prospecção: %s", exc)


def _iniciar_task_prospeccao(
    query: str, cidade: str, max_leads: int, icp_id: str | None = None,
) -> asyncio.Task:
    """Cria task isolada do ciclo de vida do request HTTP."""
    global _prospect_task
    task = asyncio.create_task(
        _run_prospect_task(query, cidade, max_leads, icp_id),
        name="prospect_pipeline",
    )
    task.add_done_callback(_on_prospect_task_done)
    _prospect_task = task
    return task


def _json(data) -> JSONResponse:
    return JSONResponse(content=data, media_type="application/json; charset=utf-8")


class StatusUpdate(BaseModel):
    status: str


class NotaUpdate(BaseModel):
    nota: str


class ConfigUpdate(BaseModel):
    delay_entre_leads: int | None = None
    timeout_lead: int | None = None
    paginas_por_lead: int | None = None
    cache_dias: int | None = None
    regioes_premium: list[str] | None = None
    icp_id: str | None = None


class GenerateRequest(BaseModel):
    mode: str | None = None
    icp_id: str | None = None
    template_id: str | None = None
    variation: str | None = None


class ActivityLogRequest(BaseModel):
    acao: str = ""
    nota: str = ""
    canal: str = "whatsapp"
    resultado: str = ""
    type: str = ""
    title: str = ""
    description: str = ""


def _carregar_leads_csv() -> list[dict]:
    import csv

    path = ROOT / "output" / "leads" / "prospeccao.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _enriquecer_leads(leads: list[dict]) -> list[dict]:
    from prospector.leads_crm import ler_notas_todos, ler_status_todos, normalizar_dominio

    statuses = ler_status_todos()
    notas = ler_notas_todos()
    enriched = []
    for lead in leads:
        domain = normalizar_dominio(lead.get("website", ""))
        st = statuses.get(domain, {})
        lead_copy = dict(lead)
        lead_copy["domain"] = domain
        lead_copy["crm_status"] = st.get("status", "pendente")
        lead_copy["abordado_em"] = st.get("abordado_em", "")
        lead_copy["notas"] = notas.get(domain, [])
        enriched.append(lead_copy)
    return enriched


def _domain_slug(domain: str) -> str:
    normalized = domain.replace("_", ".")
    return normalized.replace("www.", "").replace(".", "_")


@app.on_event("startup")
async def startup() -> None:
    from storage.database import init_database

    await init_database()


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/run")
async def run_agent(
    url: str = Query(..., min_length=4),
    max_pages: int = Query(15, ge=1, le=100),
):
    """Executa agent.py e faz streaming dos logs via SSE."""

    async def generate():
        cmd = [
            sys.executable,
            str(ROOT / "agent.py"),
            "--url",
            url,
            "--max-pages",
            str(max_pages),
            "--skip-cache",
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ROOT),
        )
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text:
                yield f"data: {json.dumps({'log': text}, ensure_ascii=False)}\n\n"
        await process.wait()
        yield f"data: {json.dumps({'done': True, 'code': process.returncode})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/history")
async def history():
    from storage.database import get_all_sites

    sites = await get_all_sites()
    return sites


@app.get("/api/briefing/{domain}")
async def get_briefing(domain: str):
    slug = _domain_slug(domain)
    path = ROOT / "output" / "briefings" / f"{slug}_briefing.md"
    if path.exists():
        return {"content": path.read_text(encoding="utf-8")}
    return {"content": None}


@app.get("/api/prompt/{domain}")
async def get_prompt(domain: str):
    slug = _domain_slug(domain)
    path = ROOT / "output" / "sites" / f"{slug}_cursor_prompt.md"
    if path.exists():
        return {"content": path.read_text(encoding="utf-8")}
    return {"content": None}


@app.get("/api/email/{domain}")
async def get_email(domain: str):
    from storage.database import get_site_email

    email = await get_site_email(domain)
    return email or {}


@app.get("/prospect")
async def prospect(
    query: str = Query("clínica odontológica"),
    cidade: str = Query("Brasília DF"),
    max_leads: int = Query(20, ge=1, le=50),
    icp_id: str | None = Query(None),
    prioridade_minima: str | None = Query(None),
    somente_whatsapp: bool = Query(False),
):
    """Inicia pipeline de prospecção em background (independente do request)."""
    global _prospect_task

    from prospector.pipeline import ler_progresso, prospeccao_em_andamento

    if prospeccao_em_andamento() and _prospect_task and not _prospect_task.done():
        return JSONResponse(
            content={
                "ok": False,
                "error": "Prospecção já em andamento",
                "status": ler_progresso(),
            },
            media_type="application/json; charset=utf-8",
        )

    _iniciar_task_prospeccao(query, cidade, max_leads, icp_id)

    return JSONResponse(
        content={
            "ok": True,
            "message": "Prospecção iniciada em background",
            "query": query,
            "cidade": cidade,
            "max_leads": max_leads,
            "icp_id": icp_id,
            "filtros": {
                "prioridade_minima": prioridade_minima,
                "somente_whatsapp": somente_whatsapp,
            },
        },
        media_type="application/json; charset=utf-8",
    )


@app.get("/api/prospect/status")
async def prospect_status():
    """Retorna estado atual da prospecção lendo progresso.json."""
    from prospector.pipeline import ler_progresso

    return JSONResponse(
        content=ler_progresso(),
        media_type="application/json; charset=utf-8",
    )


@app.get("/api/leads")
async def get_leads():
    from storage.database import get_all_leads, supabase_disponivel

    if supabase_disponivel():
        return _json(await get_all_leads())
    return _json(_enriquecer_leads(_carregar_leads_csv()))


@app.get("/api/dashboard")
async def dashboard():
    from prospector.dashboard_ops import build_operational_dashboard
    from prospector.leads_crm import calcular_metricas, ler_status_todos
    from storage.database import get_all_leads, get_lead_statuses, supabase_disponivel

    if supabase_disponivel():
        leads = await get_all_leads()
        statuses = await get_lead_statuses()
    else:
        leads = _enriquecer_leads(_carregar_leads_csv())
        statuses = ler_status_todos()
    metricas = calcular_metricas(leads, statuses)
    ops = build_operational_dashboard(leads, metricas)
    return _json({**ops, "ultimos_leads": leads[:5], "version": AGENT_VERSION})


@app.get("/api/system/status")
async def system_status():
    from config import ANTHROPIC_API_KEY
    from output.site_builder import _check_claude_code_available
    from storage.supabase_client import supabase_disponivel

    maps_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    anthropic_ok = bool(ANTHROPIC_API_KEY and not ANTHROPIC_API_KEY.startswith("sk-ant-..."))
    claude_code = _check_claude_code_available()
    supabase_ok = supabase_disponivel()

    return _json({
        "anthropic": {"ok": anthropic_ok, "label": "Online" if anthropic_ok else "Sem key"},
        "google_maps": {
            "ok": bool(maps_key),
            "label": "API key" if maps_key else "Playwright",
        },
        "supabase": {
            "ok": supabase_ok,
            "label": "Compartilhado" if supabase_ok else "SQLite local",
        },
        "claude_code": {
            "ok": claude_code,
            "label": "Instalado" if claude_code else "Não encontrado",
        },
        "version": AGENT_VERSION,
    })


@app.get("/api/config")
async def get_config():
    from config import ANTHROPIC_API_KEY, CACHE_DAYS
    from prospector.leads_crm import ler_ui_config

    cfg = ler_ui_config()
    maps_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    return _json({
        "ui": cfg,
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "anthropic_preview": (
            ANTHROPIC_API_KEY[:12] + "..." if ANTHROPIC_API_KEY else ""
        ),
        "maps_configured": bool(maps_key),
        "maps_preview": maps_key[:8] + "..." if maps_key else "",
        "cache_dias_default": CACHE_DAYS,
    })


@app.post("/api/config")
async def save_config(body: ConfigUpdate):
    from prospector.leads_crm import salvar_ui_config

    data = body.model_dump(exclude_none=True)
    return _json(salvar_ui_config(data))


@app.get("/api/leads/status")
async def get_all_status():
    from storage.database import get_lead_statuses, supabase_disponivel
    from prospector.leads_crm import ler_status_todos

    if supabase_disponivel():
        return _json(await get_lead_statuses())
    return _json(ler_status_todos())


@app.post("/api/leads/{domain}/status")
async def update_lead_status_endpoint(domain: str, body: StatusUpdate):
    from storage.database import supabase_disponivel, update_lead_status
    from prospector.leads_crm import atualizar_status

    try:
        if supabase_disponivel():
            ok = await update_lead_status(domain, body.status)
            if not ok:
                return _json({"ok": False, "error": "Lead não encontrado"})
            from prospector.activity_log import log_event
            from models.lead_status import status_label_pt
            entry = log_event(domain, "status_changed", f"Status → {status_label_pt(body.status)}", body.status)
            await _persist_activity(domain, entry)
            return _json({"ok": True, "domain": domain, "status": body.status})
        entry = atualizar_status(domain, body.status)
        from prospector.activity_log import log_event
        from models.lead_status import status_label_pt
        entry = log_event(domain, "status_changed", f"Status → {status_label_pt(body.status)}")
        return _json({"ok": True, "domain": domain, **entry})
    except ValueError as exc:
        return _json({"ok": False, "error": str(exc)})


@app.post("/api/leads/{domain}/nota")
async def add_lead_note(domain: str, body: NotaUpdate):
    from storage.database import add_lead_note, supabase_disponivel
    from prospector.leads_crm import adicionar_nota

    if supabase_disponivel():
        notas = await add_lead_note(domain, body.nota)
    else:
        notas = adicionar_nota(domain, body.nota)
    from prospector.activity_log import log_event
    entry = log_event(domain, "note_added", "Nota adicionada", body.nota[:120])
    await _persist_activity(domain, entry)
    return _json({"ok": True, "domain": domain, "notas": notas})


@app.get("/api/site/{domain}/seo")
async def get_site_seo(domain: str):
    from storage.database import get_site_data

    site_data = await get_site_data(_domain_slug(domain))
    if not site_data:
        return _json({"seo_issues": []})
    return _json({"seo_issues": site_data.seo_issues or [], "domain": domain})


@app.get("/api/whatsapp/{domain}")
async def get_whatsapp_message(domain: str):
    from prospector.message_generator import gerar_pacote_mensagens
    from storage.database import get_all_leads, get_site_data, supabase_disponivel

    if supabase_disponivel():
        leads = await get_all_leads()
        lead = next((l for l in leads if l.get("domain") == domain.replace("www.", "")), None)
        if lead and lead.get("messages_pack"):
            return lead["messages_pack"]

    site_data = await get_site_data(domain)
    if not site_data:
        return {"error": "domínio não encontrado"}
    lead_stub = {"nome": domain, "website": site_data.url, "domain": domain}
    if site_data.analysis:
        lead_stub["nome"] = site_data.analysis.get("business_name", domain)
    return gerar_pacote_mensagens(lead_stub, site_data=site_data, analysis=site_data.analysis or {})


@app.get("/api/icps")
async def list_icps_endpoint():
    from prospector.icp_loader import list_icps
    return _json([icp.to_dict() for icp in list_icps()])


@app.get("/api/icps/{icp_id}")
async def get_icp_endpoint(icp_id: str):
    from prospector.icp_loader import load_icp
    return _json(load_icp(icp_id).to_dict())


@app.get("/api/leads/{domain}")
async def get_lead_detail(domain: str):
    from config import OUTPUT_DIR
    from prospector.next_best_action import get_next_best_action
    from models.lead_status import status_label_pt
    from storage.database import get_all_leads, supabase_disponivel

    if supabase_disponivel():
        leads = await get_all_leads()
    else:
        leads = _enriquecer_leads(_carregar_leads_csv())

    lead = _find_lead(leads, domain)
    if not lead:
        return _json({"error": "Lead não encontrado"})

    slug = _domain_slug(lead.get("domain", domain))
    diag_dir = OUTPUT_DIR / "diagnoses" / slug
    proto_dir = OUTPUT_DIR / "sites" / slug / "prototype"

    lead["status_label"] = status_label_pt(lead.get("crm_status", "new"))
    lead["atividades"] = await _merge_lead_activities(domain)
    lead["next_best_action"] = get_next_best_action(lead)
    lead["diagnosis"] = {
        "exists": (diag_dir / "diagnostico.md").exists(),
        "markdown_url": f"/diagnosis/{slug}/md" if (diag_dir / "diagnostico.md").exists() else "",
        "html_url": f"/diagnosis/{slug}/html" if (diag_dir / "diagnostico.html").exists() else "",
    }
    lead["prototype"] = {
        "exists": (proto_dir / "index.html").exists(),
        "preview_url": f"/prototype/{slug}" if (proto_dir / "index.html").exists() else "",
        "quality_report": _load_json_safe(proto_dir / "quality_report.json"),
    }
    pack = lead.get("messages_pack") or {}
    if isinstance(pack, str):
        try:
            pack = json.loads(pack)
        except json.JSONDecodeError:
            pack = {}
    lead["messages_pack"] = pack
    return _json(lead)


def _find_lead(leads: list[dict], domain: str) -> dict | None:
    d = domain.replace("www.", "").replace("_", ".")
    lead = next((l for l in leads if l.get("domain", "").replace("www.", "") == d.replace("www.", "")), None)
    if not lead:
        slug = _domain_slug(domain)
        lead = next((l for l in leads if _domain_slug(l.get("domain", "")) == slug), None)
    return lead


def _load_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _normalize_activities(items: list[dict]) -> list[dict]:
    """Unifica campos de atividade para a UI."""
    seen: set[str] = set()
    out: list[dict] = []
    for a in items:
        aid = a.get("id") or f"{a.get('type', '')}-{a.get('created_at', '')}"
        if aid in seen:
            continue
        seen.add(aid)
        out.append({
            **a,
            "id": a.get("id", aid),
            "criado_em": a.get("criado_em") or a.get("created_at") or a.get("timestamp", ""),
            "tipo": a.get("tipo") or a.get("type", ""),
            "title": a.get("title") or a.get("tipo") or a.get("type", "Atividade"),
        })
    out.sort(key=lambda x: x.get("criado_em", ""), reverse=True)
    return out


async def _merge_lead_activities(domain: str) -> list[dict]:
    from prospector.activity_log import listar_atividades
    from storage.database import get_lead_activities, supabase_disponivel

    local = listar_atividades(domain)
    if supabase_disponivel():
        remote = await get_lead_activities(domain)
        return _normalize_activities(remote + local)
    return _normalize_activities(local)


async def _persist_activity(domain: str, entry: dict) -> None:
    from storage.database import append_lead_activity, supabase_disponivel

    if supabase_disponivel():
        await append_lead_activity(domain, entry)


@app.get("/prototype/{slug}")
async def serve_prototype(slug: str):
    path = ROOT / "output" / "sites" / slug / "prototype" / "index.html"
    if not path.exists():
        return _json({"error": "Protótipo não encontrado"})
    return FileResponse(path, media_type="text/html")


@app.get("/diagnosis/{slug}/html")
async def serve_diagnosis_html(slug: str):
    path = ROOT / "output" / "diagnoses" / slug / "diagnostico.html"
    if not path.exists():
        return _json({"error": "Diagnóstico não encontrado"})
    return FileResponse(path, media_type="text/html")


@app.get("/diagnosis/{slug}/md")
async def serve_diagnosis_md(slug: str):
    path = ROOT / "output" / "diagnoses" / slug / "diagnostico.md"
    if not path.exists():
        return _json({"error": "Diagnóstico não encontrado"})
    return FileResponse(path, media_type="text/markdown")


@app.post("/api/leads/{domain}/diagnosis")
async def generate_diagnosis_endpoint(domain: str):
    from output.diagnosis import generate_diagnosis, save_diagnosis
    from storage.database import get_all_leads, supabase_disponivel

    if supabase_disponivel():
        leads = await get_all_leads()
    else:
        leads = _enriquecer_leads(_carregar_leads_csv())
    lead = next((l for l in leads if l.get("domain", "").replace("www.", "") == domain.replace("www.", "")), None)
    if not lead:
        return _json({"ok": False, "error": "Lead não encontrado"})

    diagnosis = generate_diagnosis(lead)
    paths = save_diagnosis(lead, diagnosis)
    from prospector.activity_log import log_event
    from storage.artifact_index import register_diagnosis

    entry = log_event(domain, "diagnosis_generated", "Mini diagnóstico gerado", paths.get("markdown", ""))
    await _persist_activity(domain, entry)
    register_diagnosis(domain, lead, paths)
    from prospector.next_best_action import get_next_best_action
    diagnosis["json"]["next_best_action"] = get_next_best_action(lead)
    return _json({"ok": True, "diagnosis": diagnosis, "paths": paths})


@app.post("/api/leads/{domain}/prototype")
async def generate_prototype_endpoint(domain: str, body: GenerateRequest):
    from config import DEFAULT_SITE_GENERATOR_MODE
    from output.site_generator import SiteGenerator, SiteGeneratorInput, generate_site
    from storage.database import get_all_leads, get_site_data, supabase_disponivel

    site_data = await get_site_data(domain)
    if not site_data:
        return _json({"ok": False, "error": "Análise do site não encontrada. Rode prospecção ou análise primeiro."})

    lead: dict = {}
    if supabase_disponivel():
        leads = await get_all_leads()
        lead = next((l for l in leads if domain in (l.get("domain", ""), _domain_slug(l.get("domain", "")))), {})

    mode = body.mode or DEFAULT_SITE_GENERATOR_MODE
    result = await generate_site(
        site_data,
        site_data.analysis or {},
        lead=lead,
        mode=mode,
        icp_id=body.icp_id or lead.get("icp_id", "odontologia"),
        template_id=body.template_id or "",
        variation=body.variation or "",
    )
    quality: dict = {}
    if result.success and result.output_path:
        from output.quality_checklist import run_quality_check
        from pathlib import Path as P
        html = P(result.output_path).read_text(encoding="utf-8")
        quality = run_quality_check(
            html,
            business_name=lead.get("nome", domain),
            whatsapp=lead.get("whatsapp", ""),
            niche=lead.get("icp_id", "odontologia"),
            variation=body.variation or "",
            output_dir=P(result.output_path).parent,
        )
    from prospector.activity_log import log_event
    from storage.artifact_index import register_prototype

    entry = log_event(domain, "prototype_generated", f"Protótipo ({result.mode})", result.output_path or "")
    await _persist_activity(domain, entry)
    if result.success and result.output_path:
        register_prototype(
            domain,
            lead,
            output_path=result.output_path,
            variation=body.variation or "",
            quality_report=quality,
        )
    return _json({
        "ok": result.success,
        "mode": result.mode,
        "output_path": result.output_path,
        "prompt_path": result.prompt_path,
        "preview_url": f"/prototype/{_domain_slug(domain)}" if result.output_path else "",
        "quality_report": quality,
        "message": result.message,
        "error": result.error,
    })


@app.post("/api/leads/{domain}/activity")
async def register_activity_endpoint(domain: str, body: ActivityLogRequest):
    from prospector.activity_log import acao_rapida, log_event, registrar_atividade
    from storage.database import supabase_disponivel, update_lead_status

    if body.type:
        entry = log_event(domain, body.type, body.title or body.type, body.description)
        await _persist_activity(domain, entry)
        return _json({"ok": True, "entry": entry})

    status_from_acao = {
        "abordado": "contacted", "respondeu": "responded", "interessado": "interested",
        "pediu_preco": "responded", "chamar_depois": "follow_up_later", "perdido": "lost",
        "fechado": "closed", "descartado": "discarded",
        "prototipo_enviado": "prototype_sent", "proposta_enviada": "proposal_sent",
    }

    if body.acao:
        entry = acao_rapida(domain, body.acao, body.nota)
        await _persist_activity(domain, entry)
        st = status_from_acao.get(body.acao, "")
        if st and supabase_disponivel():
            await update_lead_status(domain, st, body.nota)
    else:
        entry = registrar_atividade(
            domain,
            nota=body.nota,
            canal=body.canal,
            resultado=body.resultado,
        )
        await _persist_activity(domain, entry)
        if body.resultado:
            status_map = {
                "interessado": "interested",
                "fechado": "closed",
                "perdido": "lost",
                "respondeu": "responded",
            }
            st = status_map.get(body.resultado)
            if st:
                if supabase_disponivel():
                    await update_lead_status(domain, st)
                else:
                    from prospector.leads_crm import atualizar_status
                    atualizar_status(domain, st)

    return _json({"ok": True, "entry": entry})


@app.get("/api/leads/{domain}/activity")
async def get_activity_endpoint(domain: str):
    return _json(await _merge_lead_activities(domain))


@app.get("/api/diagnoses")
async def list_diagnoses_endpoint():
    from storage.artifact_index import list_diagnoses
    from storage.database import get_all_leads, supabase_disponivel

    if supabase_disponivel():
        leads = await get_all_leads()
    else:
        leads = _enriquecer_leads(_carregar_leads_csv())
    return _json(list_diagnoses(leads))


@app.get("/api/prototypes")
async def list_prototypes_endpoint():
    from storage.artifact_index import list_prototypes
    from storage.database import get_all_leads, supabase_disponivel

    if supabase_disponivel():
        leads = await get_all_leads()
    else:
        leads = _enriquecer_leads(_carregar_leads_csv())
    return _json(list_prototypes(leads))


@app.get("/api/leads/export/csv")
async def export_leads_csv(
    status: str | None = Query(None),
    min_score: int | None = Query(None),
    icp_id: str | None = Query(None),
):
    import csv
    import io

    from fastapi.responses import StreamingResponse
    from models.lead_status import normalize_status
    from storage.database import get_all_leads, supabase_disponivel
    from storage.lead_utils import CSV_EXPORT_COLUMNS, lead_to_export_row

    if supabase_disponivel():
        leads = await get_all_leads()
    else:
        leads = _enriquecer_leads(_carregar_leads_csv())

    if status:
        norm = normalize_status(status)
        leads = [l for l in leads if normalize_status(l.get("crm_status")) == norm]
    if min_score is not None:
        leads = [l for l in leads if int(l.get("score") or l.get("opportunity_score") or 0) >= min_score]
    if icp_id:
        leads = [l for l in leads if l.get("icp_id") == icp_id]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        writer.writerow(lead_to_export_row(lead))

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
    )


@app.get("/api/env")
async def get_public_env():
    """Config pública para o frontend (sem secrets)."""
    from config import API_BASE_URL, DEFAULT_SITE_GENERATOR_MODE
    return _json({
        "api_base_url": API_BASE_URL,
        "default_site_generator_mode": DEFAULT_SITE_GENERATOR_MODE,
        "version": AGENT_VERSION,
    })


from fastapi.staticfiles import StaticFiles

_assets = ROOT / "templates" / "assets"
if _assets.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)
