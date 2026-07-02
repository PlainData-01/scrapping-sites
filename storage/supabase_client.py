"""Cliente Supabase singleton para o projeto."""

from __future__ import annotations

import os

from supabase import Client, create_client

_client: Client | None = None


def get_supabase() -> Client | None:
    """Retorna cliente Supabase ou None se não configurado."""
    global _client
    if _client is not None:
        return _client

    if os.getenv("USE_LOCAL_DB", "false").lower() in ("1", "true", "yes"):
        return None

    url = os.getenv("SUPABASE_URL", "")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )

    if not url or not key:
        return None

    _client = create_client(url, key)
    return _client


def supabase_disponivel() -> bool:
    return get_supabase() is not None
