"""Utilitários compartilhados para normalização de leads."""

from __future__ import annotations

from urllib.parse import urlparse

from models.lead_status import normalize_status


def normalize_domain(domain_or_url: str) -> str:
    d = (domain_or_url or "").strip().lower()
    if d.startswith("http"):
        d = urlparse(d).netloc
    return d.replace("www.", "").replace("_", ".")


def domain_slug(domain: str) -> str:
    return normalize_domain(domain).replace(".", "_")


def parse_json_field(value, default=None):
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        import json
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def parse_json_list_field(value, default=None) -> list:
    """Normaliza JSONB legado (objeto vazio ou dict) para lista."""
    if default is None:
        default = []
    parsed = parse_json_field(value, default=default)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        if not parsed:
            return []
        return [str(v) for v in parsed.values() if v is not None and str(v).strip()]
    if isinstance(parsed, str) and parsed.strip():
        return [parsed.strip()]
    return list(default)


def extract_city_neighborhood(endereco: str) -> tuple[str, str]:
    if not endereco:
        return "", ""
    parts = [p.strip() for p in endereco.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[-2], parts[-1] if len(parts) > 2 else ""
    return parts[0] if parts else "", ""


CSV_EXPORT_COLUMNS = [
    "id", "business_name", "niche", "icp_id", "website_url", "whatsapp", "phone",
    "city", "neighborhood", "rating", "reviews_count", "status", "opportunity_score",
    "score_reasons", "main_pain", "commercial_angle", "suggested_offer",
    "last_contacted_at", "next_follow_up_at", "created_at", "updated_at",
]


def lead_to_export_row(lead: dict) -> dict:
    """Mapeia lead da API para colunas CSV comerciais fixas."""
    city, neighborhood = extract_city_neighborhood(lead.get("endereco", ""))
    reasons = lead.get("score_reasons") or []
    if isinstance(reasons, list):
        reasons_str = " | ".join(str(r) for r in reasons)
    else:
        reasons_str = str(reasons)

    return {
        "id": lead.get("id") or lead.get("domain", ""),
        "business_name": lead.get("nome") or lead.get("business_name", ""),
        "niche": lead.get("categoria") or lead.get("niche", ""),
        "icp_id": lead.get("icp_id", "odontologia"),
        "website_url": lead.get("website", ""),
        "whatsapp": lead.get("whatsapp", ""),
        "phone": lead.get("telefone", ""),
        "city": lead.get("city") or city,
        "neighborhood": lead.get("neighborhood") or neighborhood,
        "rating": lead.get("avaliacao") or lead.get("rating", ""),
        "reviews_count": lead.get("total_avaliacoes") or lead.get("reviews_count", ""),
        "status": normalize_status(lead.get("crm_status") or "new"),
        "opportunity_score": lead.get("opportunity_score") or lead.get("score", ""),
        "score_reasons": reasons_str,
        "main_pain": lead.get("main_pain") or lead.get("problema_principal", ""),
        "commercial_angle": lead.get("commercial_angle", ""),
        "suggested_offer": lead.get("suggested_offer", ""),
        "last_contacted_at": lead.get("abordado_em") or lead.get("last_contacted_at", ""),
        "next_follow_up_at": lead.get("next_follow_up_at", ""),
        "created_at": lead.get("created_at", ""),
        "updated_at": lead.get("updated_at", ""),
    }
