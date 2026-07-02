#!/usr/bin/env python3
"""Smoke test: lead CRUD no Supabase configurado no .env."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

TEST_DOMAIN = "teste-prospect-hub.local"


async def main() -> int:
    from storage.database import (
        append_lead_activity,
        get_all_leads,
        save_lead,
        update_lead_status,
    )
    from storage.supabase_client import get_supabase, supabase_disponivel

    if not supabase_disponivel():
        print("Supabase não configurado.")
        return 1

    sb = get_supabase()
    sb.table("leads").delete().eq("domain", TEST_DOMAIN).execute()
    before = sb.table("leads").select("id", count="exact").execute().count
    print(f"Leads antes do teste: {before}")

    lead = {
        "nome": "Lead Teste PH v3.2",
        "domain": TEST_DOMAIN,
        "website": f"https://{TEST_DOMAIN}",
        "score": 75,
        "crm_status": "new",
        "main_pain": "Site desatualizado",
        "score_reasons": ["Sem HTTPS", "LCP alto"],
        "icp_id": "odontologia",
    }
    await save_lead(lead)
    fetched = next((l for l in await get_all_leads() if l.get("domain") == TEST_DOMAIN), None)
    assert fetched, "select falhou"
    print("INSERT/SELECT OK:", fetched.get("domain"), fetched.get("crm_status"))

    await update_lead_status(TEST_DOMAIN, "contacted")
    fetched2 = next((l for l in await get_all_leads() if l.get("domain") == TEST_DOMAIN), None)
    print("UPDATE status OK:", fetched2.get("crm_status"))

    entry = {
        "type": "test",
        "title": "Teste v3.2",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    activities = await append_lead_activity(TEST_DOMAIN, entry)
    print("ACTIVITY OK:", len(activities), "itens")

    all_leads = await get_all_leads()
    assert any(l.get("domain") == TEST_DOMAIN for l in all_leads)
    print("LIST OK: lead de teste visível")

    sb.table("leads").delete().eq("domain", TEST_DOMAIN).execute()
    after = sb.table("leads").select("id", count="exact").execute().count
    print(f"DELETE OK — total de leads agora: {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
