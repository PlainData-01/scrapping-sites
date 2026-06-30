"""Servidor web local para operar o scraping agent via interface visual."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)

AGENT_VERSION = "2.0"

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


async def _run_prospect_task(query: str, cidade: str, max_leads: int) -> None:
    from prospector.pipeline import executar_prospeccao

    try:
        await executar_prospeccao(
            query=query,
            cidade=cidade,
            max_leads=max_leads,
        )
    except asyncio.CancelledError:
        logger.warning("Task de prospecção cancelada — servidor continua rodando")
    except Exception as exc:
        logger.exception("Erro na prospecção: %s", exc)


def _iniciar_task_prospeccao(query: str, cidade: str, max_leads: int) -> asyncio.Task:
    """Cria task isolada do ciclo de vida do request HTTP."""
    global _prospect_task
    task = asyncio.create_task(
        _run_prospect_task(query, cidade, max_leads),
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

    _iniciar_task_prospeccao(query, cidade, max_leads)

    return JSONResponse(
        content={
            "ok": True,
            "message": "Prospecção iniciada em background",
            "query": query,
            "cidade": cidade,
            "max_leads": max_leads,
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
    from prospector.leads_crm import calcular_metricas, ler_status_todos
    from storage.database import get_all_leads, get_lead_statuses, supabase_disponivel

    if supabase_disponivel():
        leads = await get_all_leads()
        statuses = await get_lead_statuses()
    else:
        leads = _enriquecer_leads(_carregar_leads_csv())
        statuses = ler_status_todos()
    metricas = calcular_metricas(leads, statuses)
    ultimos = leads[:5]
    return _json({"metricas": metricas, "ultimos_leads": ultimos, "version": AGENT_VERSION})


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
            return _json({"ok": True, "domain": domain, "status": body.status})
        entry = atualizar_status(domain, body.status)
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
    from prospector.whatsapp_writer import gerar_mensagem_whatsapp
    from storage.database import get_site_data

    site_data = await get_site_data(domain)
    if not site_data:
        return {"error": "domínio não encontrado"}
    mensagem = gerar_mensagem_whatsapp(
        site_data=site_data,
        analysis=site_data.analysis or {},
        tem_prototipo=False,
    )
    return mensagem


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)
