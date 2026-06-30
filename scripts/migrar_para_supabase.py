"""
Migra dados do SQLite local e arquivos JSON/CSV para o Supabase.
Rodar UMA VEZ após configurar as credenciais do Supabase.

Pré-requisito:
    Executar supabase/migrate_schema.sql no SQL Editor do Supabase
    (ou supabase/schema.sql se for instalação nova).

Uso:
    python scripts/migrar_para_supabase.py
"""

from __future__ import annotations

import asyncio
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIGRATE_SQL = ROOT / "supabase" / "migrate_schema.sql"


def _normalizar_dominio(url: str) -> str:
    if url.startswith("http"):
        return urlparse(url).netloc.replace("www.", "").lower()
    return url.replace("www.", "").replace("_", ".").lower()


def _erro_schema(exc: Exception) -> bool:
    msg = str(exc)
    return (
        "PGRST204" in msg
        or "42703" in msg
        or "Could not find" in msg
        or "does not exist" in msg
    )


def _verificar_schema(sb) -> bool:
    """Confirma que colunas extras existem antes de migrar."""
    try:
        sb.table("sites").select("pages,assets,screenshots,status").limit(1).execute()
        sb.table("leads").select("notas,status_processamento,domain").limit(1).execute()
        return True
    except Exception as exc:
        if _erro_schema(exc):
            print("\n[ERRO] Schema incompleto no Supabase!")
            print(f"   Arquivo: {MIGRATE_SQL}")
            print("   1. Abra Supabase Dashboard -> SQL Editor")
            print("   2. Cole o conteudo de supabase/migrate_schema.sql")
            print("   3. Clique Run e aguarde ~10 segundos")
            print("   4. Rode este script novamente\n")
            return False
        raise


def _upsert_com_retry(sb, tabela: str, data: dict, on_conflict: str, tentativas: int = 3):
    for i in range(tentativas):
        try:
            return sb.table(tabela).upsert(data, on_conflict=on_conflict).execute()
        except Exception as exc:
            if _erro_schema(exc) and i < tentativas - 1:
                time.sleep(5)
                continue
            raise


async def migrar() -> None:
    from config import DATABASE_PATH, OUTPUT_DIR
    from storage.database import (
        _lead_dict_to_supabase,
        _site_data_to_supabase_row,
        _supabase_upsert_resiliente,
    )
    from storage.supabase_client import get_supabase, supabase_disponivel

    if not supabase_disponivel():
        print("[ERRO] Configure SUPABASE_URL e SUPABASE_KEY no .env primeiro")
        return

    sb = get_supabase()

    db_path = DATABASE_PATH
    if not db_path.exists():
        print(f"[AVISO] Banco SQLite nao encontrado em {db_path} — pulando sites")
    else:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM crawled_sites ORDER BY crawled_at")
        sites = cursor.fetchall()
        print(f"Migrando {len(sites)} sites do SQLite...")

        erros_sites = 0
        for site in sites:
            try:
                data = json.loads(site["data_json"]) if site["data_json"] else {}
                from config import SiteData

                site_data = SiteData(
                    url=data.get("url", site["url"]),
                    domain=data.get("domain", _normalizar_dominio(site["url"])),
                    pages=data.get("pages", []),
                    assets=data.get("assets", []),
                    contacts=data.get("contacts", {}),
                    colors=data.get("colors", []),
                    fonts=data.get("fonts", []),
                    seo_issues=data.get("seo_issues", []),
                    screenshots=data.get("screenshots", {}),
                    analysis=data.get("analysis"),
                    proposal_pdf_path=data.get("proposal_pdf_path"),
                    email_content=data.get("email_content"),
                    briefing_path=data.get("briefing_path"),
                    site_project_path=data.get("site_project_path"),
                )
                row = _site_data_to_supabase_row(site_data)
                _supabase_upsert_resiliente(sb, "sites", row, "url")
            except Exception as exc:
                print(f"  [AVISO] Erro ao migrar site {site['url']}: {exc}")
                erros_sites += 1

        print(f"[OK] {len(sites) - erros_sites} sites migrados ({erros_sites} erros)")
        conn.close()

    csv_path = OUTPUT_DIR / "leads" / "prospeccao.csv"
    status_path = OUTPUT_DIR / "leads" / "status.json"
    notas_path = OUTPUT_DIR / "leads" / "notas.json"

    statuses: dict = {}
    notas: dict = {}
    if status_path.exists():
        statuses = json.loads(status_path.read_text(encoding="utf-8"))
    if notas_path.exists():
        notas = json.loads(notas_path.read_text(encoding="utf-8"))

    if not csv_path.exists():
        print("[AVISO] CSV de leads nao encontrado — pulando leads")
        return

    with csv_path.open(encoding="utf-8") as f:
        leads = list(csv.DictReader(f))

    print(f"Migrando {len(leads)} leads do CSV...")
    erros_leads = 0
    for lead in leads:
        try:
            domain = _normalizar_dominio(lead.get("website", ""))
            st = statuses.get(domain, {})
            lead_notas = notas.get(domain, [])
            data = _lead_dict_to_supabase(lead)
            data["status_crm"] = st.get("status", "pendente")
            data["abordado_em"] = st.get("abordado_em") or None
            data["notas"] = lead_notas
            if lead_notas:
                data["nota"] = lead_notas[-1].get("texto", "")
            _supabase_upsert_resiliente(sb, "leads", data, "domain")
        except Exception as exc:
            print(f"  [AVISO] Erro ao migrar lead {lead.get('nome', '?')}: {exc}")
            erros_leads += 1

    print(f"[OK] {len(leads) - erros_leads} leads migrados ({erros_leads} erros)")
    print("\nMigracao concluida! Reinicie o api.py em ambas as maquinas.")


if __name__ == "__main__":
    asyncio.run(migrar())
