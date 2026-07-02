#!/usr/bin/env python3
"""Aplica supabase/migrations/apply_all_v32.sql no projeto do .env (idempotente)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "apply_all_v32.sql"


def _project_ref() -> str:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if not url:
        raise SystemExit("SUPABASE_URL ausente no .env")
    host = urlparse(url).hostname or ""
    ref = host.split(".")[0]
    if not ref:
        raise SystemExit(f"Não foi possível extrair project ref de {url}")
    return ref


def _connection_urls(ref: str, password: str) -> list[str]:
    enc = quote_plus(password)
    return [
        f"postgresql://postgres:{enc}@db.{ref}.supabase.co:5432/postgres?sslmode=require",
        f"postgresql://postgres.{ref}:{enc}@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?sslmode=require",
        f"postgresql://postgres.{ref}:{enc}@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require",
    ]


def _connect():
    import psycopg2

    db_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if db_url:
        return psycopg2.connect(db_url)

    password = os.getenv("SUPABASE_DB_PASSWORD", "").strip()
    if not password:
        service = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if service.startswith("eyJ"):
            raise SystemExit(
                "SUPABASE_DB_PASSWORD ausente. SUPABASE_SERVICE_ROLE_KEY é a chave da API (JWT), "
                "não a senha do Postgres. Em Project Settings → Database, copie a "
                "'Database password' para SUPABASE_DB_PASSWORD no .env e rode de novo."
            )
        raise SystemExit(
            "Defina SUPABASE_DB_PASSWORD ou DATABASE_URL no .env "
            "(Settings → Database → Database password no Supabase)."
        )

    ref = _project_ref()
    last_err: Exception | None = None
    for url in _connection_urls(ref, password):
        try:
            return psycopg2.connect(url)
        except Exception as exc:
            last_err = exc
    raise SystemExit(f"Falha ao conectar no Postgres ({ref}): {last_err}")


def _columns(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row[0] for row in cur.fetchall()]


def main() -> int:
    load_dotenv(ROOT / ".env")
    if not MIGRATION.is_file():
        raise SystemExit(f"Migration não encontrada: {MIGRATION}")

    sql = MIGRATION.read_text(encoding="utf-8")
    conn = _connect()
    try:
        before_leads = _columns(conn, "leads")
        before_sites = _columns(conn, "sites")
        print(f"Projeto: {_project_ref()}")
        print(f"Colunas leads antes ({len(before_leads)}): {', '.join(before_leads)}")
        print(f"Colunas sites antes ({len(before_sites)}): {', '.join(before_sites)}")

        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

        after_leads = _columns(conn, "leads")
        after_sites = _columns(conn, "sites")
        added_leads = [c for c in after_leads if c not in before_leads]
        added_sites = [c for c in after_sites if c not in before_sites]

        print(f"\nMigration aplicada: {MIGRATION.name}")
        if added_leads:
            print(f"Colunas adicionadas em leads: {', '.join(added_leads)}")
        else:
            print("Nenhuma coluna nova em leads (já estava atualizado).")
        if added_sites:
            print(f"Colunas adicionadas em sites: {', '.join(added_sites)}")
        else:
            print("Nenhuma coluna nova em sites.")
        print(f"Colunas leads depois ({len(after_leads)}): {', '.join(after_leads)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
