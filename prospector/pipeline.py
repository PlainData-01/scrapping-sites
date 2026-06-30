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
    "prioridade", "score", "nome", "plataforma_detectada",
    "avaliacao", "total_avaliacoes", "telefone", "website",
    "endereco", "google_maps_url", "qualificado",
    "motivo_descarte", "problema_principal",
    "mensagem_whatsapp", "whatsapp_link", "status",
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
) -> dict[str, Any]:
    """Processa um lead com timeout máximo. Se travar, descarta e continua."""
    try:
        site_data = await asyncio.wait_for(
            _run_agent_safe(
                url=lead.website,
                max_pages=8,
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


def _montar_resultado_lead(lead: Lead, processamento: dict[str, Any]) -> dict[str, Any]:
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
    mensagem = gerar_mensagem_whatsapp(
        site_data=site_data,
        analysis=analysis,
        tem_prototipo=False,
        telefone_fallback=lead.telefone,
        plataforma_detectada=lead.plataforma_detectada,
        site_terceirizado=lead.site_terceirizado,
    )

    whatsapp = lead.telefone or mensagem["whatsapp_numero"]
    whatsapp_link = mensagem["whatsapp_link"]
    if not whatsapp_link and whatsapp:
        from prospector.whatsapp_writer import _build_whatsapp_link
        whatsapp_link = _build_whatsapp_link(whatsapp, mensagem["mensagem_curta"])

    return {
        **base,
        "whatsapp": whatsapp,
        "problemas_seo": len(site_data.seo_issues or []),
        "problema_principal": mensagem["problema_detectado"],
        "mensagem_whatsapp": mensagem["mensagem_curta"],
        "mensagem_completa": mensagem["mensagem_completa"],
        "whatsapp_link": whatsapp_link,
        "mensagem_followup": mensagem.get("mensagem_followup", ""),
        "whatsapp_followup_link": mensagem.get("whatsapp_followup_link", ""),
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
    delay_entre_leads: int = 5,
    output_csv: str = DEFAULT_OUTPUT_CSV,
) -> None:
    """Executa prospecção completa, persistindo progresso a cada etapa."""
    progresso = ProgressoProspeccao.iniciar(query, cidade, max_leads)

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

                processamento = await _processar_lead_com_timeout(lead)

                # a) Montar resultado — b) Salvar IMEDIATAMENTE (antes de qualquer outra op)
                resultado = _montar_resultado_lead(lead, processamento)
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
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(resultados)
