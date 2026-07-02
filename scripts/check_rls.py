#!/usr/bin/env python3
import os
from pathlib import Path
from urllib.parse import quote_plus

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
ref = os.environ["SUPABASE_URL"].replace("https://", "").split(".")[0]
pwd = os.environ["SUPABASE_DB_PASSWORD"]
url = f"postgresql://postgres:{quote_plus(pwd)}@db.{ref}.supabase.co:5432/postgres?sslmode=require"
conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute(
    """
    SELECT c.relname, c.relrowsecurity
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname IN ('leads', 'sites')
    """
)
for name, rls in cur.fetchall():
    print(f"RLS {name}: {'enabled' if rls else 'disabled'}")
conn.close()
