"""
Pipeline de prospecção: Google Maps → Scraping → WhatsApp.
Processa leads em sequência, com delay entre cada um.
Progresso persistido em output/leads/progresso.json para polling.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent import _run_agent_safe
from config import OUTPUT_DIR
from crawler.scraper import close_browser
from prospector.google_maps import (
    Lead,
    _limpar_telefone,
    _site_acessivel,
    ajustar_score_pos_scraping,
    buscar_leads_com_descartados,
    lead_para_dict,
)
from prospector.whatsapp_writer import gerar_mensagem_whatsapp

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_CSV = str(OUTPUT_DIR / "leads" / "prospeccao.csv")
PROGRESS_FILE = OUTPUT_DIR / "leads" / "progresso.json"

CSV_FIELDNAMES = [
    "prioridade", "score", "opportunity_score", "nome", "plataforma_detectada",
    "avaliacao", "total_avaliacoes", "telefone", "whatsapp", "website",
    "endereco", "google_maps", "qualificado", "motivo_descarte",
    "problema_principal", "main_pain", "commercial_angle", "suggested_offer",
    "icp_id", "score_reasons", "mensagem_whatsapp", "whatsapp_link",
    "status", "crm_status", "created_at", "updated_at",
]


def _garantir_pasta_leads() -> None:
    (OUTPUT_DIR / "leads").mkdir(parents=True, exist_ok=True)


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _salvar_progresso(estado: dict[str, Any]) -> None:
    """Persiste progresso em disco (síncrono, UTF-8)."""
    _garantir_pasta_leads()
    estado["atualizado_em"] = _agora_iso()
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(PROGRESS_FILE)


async def salvar_progresso_protegido(estado: dict[str, Any]) -> None:
    """
    Persiste progresso protegido contra cancelamento da task.
    Usa shield + thread para garantir flush em disco antes de continuar.
    """
    try:
        await asyncio.shield(asyncio.to_thread(_salvar_progresso, estado))
    except asyncio.CancelledError:
        # Fallback síncrono — não re-propaga para o uvicorn
        _salvar_progresso(estado)
        logger.warning("Progresso salvo via fallback após cancelamento")
    except Exception as exc:
        logger.error("Falha ao salvar progresso protegido: %s", exc)
        _salvar_progresso(estado)


def ler_progresso() -> dict[str, Any]:
    """Lê o estado atual da prospecção do arquivo JSON."""
    if not PROGRESS_FILE.exists():
        return {"status": "idle"}
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Erro ao ler progresso: %s", exc)
        return {"status": "idle"}


class ProgressoProspeccao:
    """Gerencia persistência do progresso em disco."""

    def __init__(self, estado: dict[str, Any]) -> None:
        self.estado = estado

    @classmethod
    def iniciar(cls, query: str, cidade: str, max_leads: int) -> ProgressoProspeccao:
        estado: dict[str, Any] = {
            "status": "running",
            "query": query,
            "cidade": cidade,
            "max_leads": max_leads,
            "total": 0,
            "atual": 0,
            "nome_atual": "",
            "leads": [],
            "descartados": [],
            "logs": [],
            "mensagem": "Iniciando prospecção...",
            "csv_path": "",
            "erro": None,
            "iniciado_em": _agora_iso(),
            "atualizado_em": _agora_iso(),
            "finalizado_em": None,
        }
        _salvar_progresso(estado)
        return cls(estado)

    def log(self, msg: str, level: str = "info") -> None:
        self.estado["logs"].append({"msg": msg, "level": level})
        _salvar_progresso(self.estado)

    async def log_async(self, msg: str, level: str = "info") -> None:
        self.estado["logs"].append({"msg": msg, "level": level})
        await salvar_progresso_protegido(self.estado)

    def atualizar(self, **kwargs: Any) -> None:
        self.estado.update(kwargs)
        _salvar_progresso(self.estado)

    async def atualizar_async(self, **kwargs: Any) -> None:
        self.estado.update(kwargs)
        await salvar_progresso_protegido(self.estado)

    def adicionar_lead(self, lead: dict[str, Any]) -> None:
        self.estado["leads"].append(lead)
        _salvar_progresso(self.estado)

    async def adicionar_lead_imediato(self, lead: dict[str, Any]) -> None:
        """Salva lead no progresso imediatamente (operação prioritária)."""
        self.estado["leads"].append(lead)
        await salvar_progresso_protegido(self.estado)

    async def finalizar_async(
        self,
        status: str = "done",
        csv_path: str = "",
        erro: str | None = None,
    ) -> None:
        self._aplicar_finalizacao(status, csv_path, erro)
        await salvar_progresso_protegido(self.estado)

    def finalizar(
        self,
        status: str = "done",
        csv_path: str = "",
        erro: str | None = None,
    ) -> None:
        self._aplicar_finalizacao(status, csv_path, erro)
        _salvar_progresso(self.estado)

    def _aplicar_finalizacao(
        self,
        status: str,
        csv_path: str,
        erro: str | None,
    ) -> None:
        self.estado["status"] = status
        self.estado["finalizado_em"] = _agora_iso()
        if csv_path:
            self.estado["csv_path"] = csv_path
        if erro:
            self.estado["erro"] = erro
        if status == "done":
            self.estado["mensagem"] = (
                f"Concluído — {len(self.estado['leads'])} leads processados"
            )


def prospeccao_em_andamento() -> bool:
    """Verifica se há prospecção rodando segundo o arquivo de progresso."""
    estado = ler_progresso()
    return estado.get("status") == "running"


async def _processar_lead_com_timeout(
    lead: Lead,
    timeout_segundos: int = 180,
    max_pages: int = 8,
) -> dict[str, Any]:
    """Processa um lead com timeout máximo. Se travar, descarta e continua."""
    try:
        site_data = await asyncio.wait_for(
            _run_agent_safe(
                url=lead.website,
                max_pages=max_pages,
                skip_cache=False,
                interactive=False,
                prospect_mode=True,
            ),
            timeout=timeout_segundos,
        )
        if site_data.analysis:
            from output.email_writer import generate_prospecting_email

            site_data.email_content = generate_prospecting_email(
                site_data.analysis, site_data,
            )
        return {"sucesso": True, "site_data": site_data}
    except asyncio.TimeoutError:
        logger.warning(
            "⏱ Timeout após %ds processando %s (%s) — pulando para o próximo",
            timeout_segundos, lead.nome, lead.website,
        )
        return {"sucesso": False, "erro": f"Timeout após {timeout_segundos}s"}
    except asyncio.CancelledError:
        logger.warning("Processamento de %s cancelado", lead.nome)
        raise
    except Exception as e:
        logger.error("❌ Erro ao processar %s: %s", lead.nome, e)
        return {"sucesso": False, "erro": str(e)}


def _montar_resultado_lead(
    lead: Lead,
    processamento: dict[str, Any],
    icp_id: str = "odontologia",
) -> dict[str, Any]:
    """Monta dict de resultado a partir do lead e do processamento."""
    base = {
        "nome": lead.nome,
        "website": lead.website,
        "whatsapp": _limpar_telefone(lead.telefone) or lead.telefone,
        "endereco": lead.endereco,
        "google_maps": lead.google_maps_url,
        "avaliacao": lead.avaliacao,
        "total_avaliacoes": lead.total_avaliacoes,
        "score": lead.score,
        "prioridade": lead.prioridade,
        "plataforma_detectada": lead.plataforma_detectada,
        "qualificado": lead.qualificado,
        "motivo_descarte": lead.motivo_descarte,
        "score_motivo": _principal_motivo_score(lead),
        "site_terceirizado": lead.site_terceirizado,
        "icp_id": icp_id,
        "categoria": lead.categoria,
    }

    if not processamento.get("sucesso"):
        return {
            **base,
            "status": "erro",
            "erro": processamento.get("erro", "Erro desconhecido"),
        }

    site_data = processamento["site_data"]
    analysis = dict(site_data.analysis or {})
    if lead.plataforma_detectada and not analysis.get("platform"):
        analysis["platform"] = lead.plataforma_detectada

    from parser.commercial_analysis import analyze_site_commercial
    from prospector.icp_loader import load_icp
    from prospector.message_generator import gerar_pacote_mensagens
    from prospector.scoring import compute_score

    icp = load_icp(icp_id)
    commercial = analyze_site_commercial(site_data)
    score_result = compute_score(
        icp,
        plataforma=lead.plataforma_detectada,
        avaliacao=lead.avaliacao,
        total_avaliacoes=lead.total_avaliacoes,
        has_website=bool(lead.website),
        has_whatsapp=commercial.has_visible_whatsapp,
        has_visible_cta=commercial.has_clear_cta,
        has_contact_form=commercial.has_contact_form,
        has_meta_pixel=commercial.has_meta_pixel,
        has_gtm=commercial.has_google_tag_manager,
        has_service_pages=commercial.has_service_pages,
        has_social_proof=commercial.has_social_proof,
        old_visual_site=commercial.old_visual_site,
        weak_mobile_cta=commercial.weak_mobile_cta,
        endereco=lead.endereco,
        has_phone=bool(_limpar_telefone(lead.telefone)),
        commercial_issues=commercial.commercial_issues,
    )

    lead.score = score_result.opportunity_score
    lead.prioridade = (
        "alta" if lead.score >= 65 else "media" if lead.score >= 35 else "baixa"
    )

    lead_dict = {
        **base,
        "score": score_result.opportunity_score,
        "opportunity_score": score_result.opportunity_score,
        "prioridade": lead.prioridade,
        "score_reasons": score_result.score_reasons,
        "main_pain": score_result.main_pain,
        "commercial_angle": score_result.commercial_angle,
        "suggested_offer": score_result.suggested_offer,
        "commercial_analysis": commercial.to_dict(),
        "problema_principal": score_result.main_pain,
        "score_motivo": score_result.score_reasons[0] if score_result.score_reasons else _principal_motivo_score(lead),
    }

    messages = gerar_pacote_mensagens(lead_dict, site_data=site_data, analysis=analysis)
    lead_dict["messages_pack"] = messages
    lead_dict["mensagem_whatsapp"] = messages["mensagem_curta"]
    lead_dict["mensagem_completa"] = messages["mensagem_consultiva"]

    whatsapp = lead.telefone or messages.get("whatsapp_numero", "")
    whatsapp_link = messages.get("whatsapp_link_curta", "")
    if not whatsapp_link and whatsapp:
        from prospector.whatsapp_writer import _build_whatsapp_link
        whatsapp_link = _build_whatsapp_link(whatsapp, messages["mensagem_curta"])

    return {
        **lead_dict,
        "whatsapp": whatsapp,
        "problemas_seo": len(site_data.seo_issues or []),
        "whatsapp_link": whatsapp_link,
        "mensagem_followup": messages.get("followup_1", ""),
        "status": "pronto",
    }


def _principal_motivo_score(lead: Lead) -> str:
    """Retorna o principal motivo de pontuação do lead."""
    detalhes = lead.score_detalhes or {}
    if "plataforma" in detalhes:
        return detalhes["plataforma"].get("motivo", "")
    for key in ("avaliacao", "volume", "whatsapp", "localizacao"):
        if key in detalhes:
            return detalhes[key].get("motivo", "")
    return ""


async def executar_prospeccao(
    query: str = "clínica odontológica",
    cidade: str = "Brasília DF",
    max_leads: int = 20,
    delay_entre_leads: int | None = None,
    output_csv: str = DEFAULT_OUTPUT_CSV,
    icp_id: str | None = None,
    max_pages: int | None = None,
    timeout_lead: int | None = None,
) -> None:
    """Executa prospecção completa, persistindo progresso a cada etapa."""
    from prospector.icp_loader import load_icp
    from prospector.leads_crm import ler_ui_config

    ui = ler_ui_config()
    icp = load_icp(icp_id or ui.get("icp_id"))
    if not icp_id:
        icp_id = icp.id
    if query == "clínica odontológica" and icp.default_query:
        query = icp.default_query
    if cidade == "Brasília DF" and icp.default_location:
        cidade = f"{icp.default_location} DF"
    delay_entre_leads = delay_entre_leads if delay_entre_leads is not None else int(ui.get("delay_entre_leads", 5))
    max_pages = max_pages or int(ui.get("paginas_por_lead", 8))
    timeout_lead = timeout_lead or int(ui.get("timeout_lead", 180))

    progresso = ProgressoProspeccao.iniciar(query, cidade, max_leads)
    progresso.estado["icp_id"] = icp_id

    try:
        logger.info(
            "Iniciando prospecção: query='%s', cidade='%s', max=%d",
            query, cidade, max_leads,
        )
        await progresso.log_async(f"Buscando leads: {query} em {cidade}...")
        await progresso.atualizar_async(
            mensagem=f"Buscando leads: {query} em {cidade}...",
        )

        leads, descartados = await buscar_leads_com_descartados(
            query=query, cidade=cidade, max_results=max_leads,
        )

        await progresso.atualizar_async(
            total=len(leads),
            descartados=[lead_para_dict(l) for l in descartados],
            mensagem=(
                f"{len(leads)} leads qualificados de {max_leads} solicitados | "
                f"{len(descartados)} descartados na busca"
            ),
        )
        await progresso.log_async(
            f"{len(leads)} leads qualificados de {max_leads} solicitados | "
            f"{len(descartados)} descartados na busca"
        )

        if len(leads) < max_leads:
            await progresso.log_async(
                f"⚠ Apenas {len(leads)} leads passaram nos filtros "
                f"(site + HTTPS + qualificação). Tente ampliar a busca ou a cidade.",
                "warning",
            )

        if not leads:
            await progresso.log_async("Nenhum lead qualificado encontrado.", "warning")
            await progresso.finalizar_async(status="done")
            return

        resultados: list[dict[str, Any]] = []

        for i, lead in enumerate(leads, 1):
            try:
                await progresso.atualizar_async(
                    atual=i,
                    nome_atual=lead.nome,
                    mensagem=f"Processando [{i}/{len(leads)}]: {lead.nome}",
                )
                await progresso.log_async(
                    f"[{i}/{len(leads)}] Processando: {lead.nome} ({lead.website})"
                )

                acessivel, motivo_site = await _site_acessivel(lead.website)
                if not acessivel:
                    resultado = {
                        "nome": lead.nome,
                        "website": lead.website,
                        "whatsapp": _limpar_telefone(lead.telefone) or lead.telefone,
                        "endereco": lead.endereco,
                        "google_maps": lead.google_maps_url,
                        "avaliacao": lead.avaliacao,
                        "total_avaliacoes": lead.total_avaliacoes,
                        "score": lead.score,
                        "prioridade": lead.prioridade,
                        "plataforma_detectada": lead.plataforma_detectada,
                        "status": "erro",
                        "erro": f"Site inacessível: {motivo_site}",
                    }
                    resultados.append(resultado)
                    await progresso.adicionar_lead_imediato(resultado)
                    try:
                        from storage.database import save_lead
                        await save_lead(resultado)
                    except Exception as exc:
                        logger.warning("Falha ao salvar lead no banco: %s", exc)
                    await progresso.log_async(
                        f"⏭ {lead.nome} — site inacessível ({motivo_site})",
                        "warning",
                    )
                    continue

                processamento = await _processar_lead_com_timeout(
                    lead, timeout_segundos=timeout_lead, max_pages=max_pages,
                )

                # a) Montar resultado — b) Salvar IMEDIATAMENTE (antes de qualquer outra op)
                resultado = _montar_resultado_lead(lead, processamento, icp_id=icp_id)
                if processamento.get("sucesso"):
                    site_data = processamento["site_data"]
                    ajustar_score_pos_scraping(
                        lead, len(site_data.seo_issues or []),
                    )
                    resultado["score"] = lead.score
                    resultado["prioridade"] = lead.prioridade
                resultados.append(resultado)
                await progresso.adicionar_lead_imediato(resultado)

                try:
                    from storage.database import save_lead
                    await save_lead(resultado)
                except Exception as exc:
                    logger.warning("Falha ao salvar lead no banco: %s", exc)

                # Operações secundárias só depois do persist
                try:
                    await close_browser()
                except asyncio.CancelledError:
                    logger.warning(
                        "close_browser cancelado após salvar lead %s", lead.nome,
                    )

                if processamento.get("sucesso"):
                    lead.status = "processado"
                    await progresso.log_async(
                        f"✅ {lead.nome} — {resultado.get('problema_principal', '')}"
                    )
                else:
                    lead.status = "erro"
                    await progresso.log_async(
                        f"❌ Erro ao processar {lead.nome}: {processamento.get('erro')}",
                        "error",
                    )

                if i < len(leads):
                    await progresso.log_async(
                        f"Aguardando {delay_entre_leads}s antes do próximo lead..."
                    )
                    await asyncio.sleep(delay_entre_leads)

            except asyncio.CancelledError:
                logger.warning(
                    "Prospecção cancelada no lead %d/%d (%s) — progresso já salvo",
                    i, len(leads), lead.nome,
                )
                progresso.estado["erro"] = "Cancelada"
                progresso.estado["status"] = "error"
                await salvar_progresso_protegido(progresso.estado)
                return

        csv_path = ""
        if resultados:
            _salvar_resultados_csv(resultados, output_csv)
            csv_path = output_csv
            await progresso.log_async(f"CSV salvo em: {output_csv}")

        await progresso.finalizar_async(status="done", csv_path=csv_path)

    except asyncio.CancelledError:
        logger.warning("Prospecção cancelada — encerrando sem propagar erro")
        try:
            progresso.estado.setdefault("logs", []).append({
                "msg": "Prospecção cancelada.",
                "level": "warning",
            })
            progresso.estado["status"] = "error"
            progresso.estado["erro"] = "Cancelada"
            progresso.estado["finalizado_em"] = _agora_iso()
            _salvar_progresso(progresso.estado)
        except Exception as save_exc:
            logger.error("Falha ao salvar progresso no cancelamento: %s", save_exc)
    except Exception as exc:
        logger.exception("Erro fatal na prospecção: %s", exc)
        try:
            await progresso.log_async(f"Erro fatal: {exc}", "error")
            await progresso.finalizar_async(status="error", erro=str(exc))
        except Exception:
            progresso.estado["status"] = "error"
            progresso.estado["erro"] = str(exc)
            _salvar_progresso(progresso.estado)


async def prospectar_stream(
    query: str = "clínica odontológica",
    cidade: str = "Brasília DF",
    max_leads: int = 20,
    delay_entre_leads: int = 5,
    output_csv: str = DEFAULT_OUTPUT_CSV,
) -> AsyncIterator[dict[str, Any]]:
    """Generator async que emite eventos de progresso para SSE."""
    logger.info(
        "Iniciando prospecção: query='%s', cidade='%s', max=%d",
        query, cidade, max_leads,
    )
    yield {"log": f"Buscando leads: {query} em {cidade}..."}

    leads, descartados = await buscar_leads_com_descartados(
        query=query, cidade=cidade, max_results=max_leads,
    )

    yield {
        "tipo": "leads_encontrados",
        "total": len(leads),
        "descartados": [lead_para_dict(l) for l in descartados],
    }
    yield {
        "log": (
            f"{len(leads)} leads qualificados | {len(descartados)} descartados na busca"
        ),
    }

    if not leads:
        yield {"log": "Nenhum lead qualificado encontrado.", "level": "warning"}
        yield {"tipo": "done", "total": 0}
        return

    resultados: list[dict[str, Any]] = []

    for i, lead in enumerate(leads, 1):
        yield {
            "tipo": "processando",
            "atual": i,
            "total": len(leads),
            "nome": lead.nome,
        }
        yield {"log": f"[{i}/{len(leads)}] Processando: {lead.nome} ({lead.website})"}

        processamento = await _processar_lead_com_timeout(lead)
        await close_browser()

        resultado = _montar_resultado_lead(lead, processamento)
        resultados.append(resultado)

        if processamento.get("sucesso"):
            lead.status = "processado"
            yield {
                "tipo": "lead_concluido",
                "lead": resultado,
            }
            yield {"log": f"✅ {lead.nome} — {resultado.get('problema_principal', '')}"}
        else:
            lead.status = "erro"
            yield {
                "tipo": "lead_concluido",
                "lead": resultado,
            }
            yield {
                "log": f"❌ Erro ao processar {lead.nome}: {processamento.get('erro')}",
                "level": "error",
            }

        if i < len(leads):
            yield {"log": f"Aguardando {delay_entre_leads}s antes do próximo lead..."}
            await asyncio.sleep(delay_entre_leads)

    if resultados:
        _salvar_resultados_csv(resultados, output_csv)
        yield {"log": f"CSV salvo em: {output_csv}"}

    yield {"tipo": "done", "total": len(resultados)}


async def prospectar(
    query: str = "clínica odontológica",
    cidade: str = "Brasília DF",
    max_leads: int = 20,
    delay_entre_leads: int = 5,
    output_csv: str = DEFAULT_OUTPUT_CSV,
) -> list[dict[str, Any]]:
    """Fluxo completo de prospecção (sem streaming)."""
    resultados: list[dict[str, Any]] = []
    async for event in prospectar_stream(
        query=query,
        cidade=cidade,
        max_leads=max_leads,
        delay_entre_leads=delay_entre_leads,
        output_csv=output_csv,
    ):
        if event.get("tipo") == "lead_concluido":
            resultados.append(event["lead"])
    return resultados


def _salvar_resultados_csv(resultados: list[dict[str, Any]], path: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not resultados:
        return
    rows = []
    for r in resultados:
        row = dict(r)
        for key in ("score_reasons", "commercial_analysis", "messages_pack"):
            if isinstance(row.get(key), (list, dict)):
                row[key] = json.dumps(row[key], ensure_ascii=False)
        row.setdefault("opportunity_score", row.get("score", 0))
        row.setdefault("crm_status", "new")
        rows.append(row)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
