"""Índice de diagnósticos e protótipos gerados."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR
from storage.lead_utils import domain_slug, normalize_domain

INDEX_FILE = OUTPUT_DIR / "leads" / "artifacts_index.json"

EXPORT_FIELDS_DIAGNOSIS = ["domain", "business_name", "icp_id", "score", "status", "created_at", "type", "url"]
EXPORT_FIELDS_PROTOTYPE = ["domain", "business_name", "icp_id", "score", "status", "created_at", "variation", "url", "ready"]


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ler() -> dict[str, list[dict]]:
    if not INDEX_FILE.exists():
        return {"diagnoses": [], "prototypes": []}
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return {
            "diagnoses": data.get("diagnoses") or [],
            "prototypes": data.get("prototypes") or [],
        }
    except (json.JSONDecodeError, OSError):
        return {"diagnoses": [], "prototypes": []}


def _salvar(data: dict[str, list[dict]]) -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INDEX_FILE)


def register_diagnosis(domain: str, lead: dict, paths: dict[str, str]) -> dict:
    domain = normalize_domain(domain)
    slug = domain_slug(domain)
    entry = {
        "domain": domain,
        "slug": slug,
        "business_name": lead.get("nome") or lead.get("business_name", domain),
        "icp_id": lead.get("icp_id", "odontologia"),
        "score": lead.get("score") or lead.get("opportunity_score", 0),
        "status": lead.get("crm_status", "new"),
        "type": "diagnosis",
        "created_at": _agora(),
        "url_html": f"/diagnosis/{slug}/html",
        "url_md": f"/diagnosis/{slug}/md",
        "paths": paths,
    }
    data = _ler()
    data["diagnoses"] = [d for d in data["diagnoses"] if d.get("domain") != domain]
    data["diagnoses"].insert(0, entry)
    _salvar(data)
    return entry


def register_prototype(
    domain: str,
    lead: dict,
    *,
    output_path: str,
    variation: str = "",
    quality_report: dict | None = None,
) -> dict:
    domain = normalize_domain(domain)
    slug = domain_slug(domain)
    entry = {
        "domain": domain,
        "slug": slug,
        "business_name": lead.get("nome") or lead.get("business_name", domain),
        "icp_id": lead.get("icp_id", "odontologia"),
        "score": lead.get("score") or lead.get("opportunity_score", 0),
        "status": lead.get("crm_status", "new"),
        "type": "prototype",
        "variation": variation,
        "created_at": _agora(),
        "url": f"/prototype/{slug}",
        "output_path": output_path,
        "ready_to_send": (quality_report or {}).get("ready_to_send", True),
        "quality_warning": (quality_report or {}).get("warning", ""),
    }
    data = _ler()
    data["prototypes"] = [p for p in data["prototypes"] if p.get("domain") != domain]
    data["prototypes"].insert(0, entry)
    _salvar(data)
    return entry


def scan_filesystem(leads: list[dict] | None = None) -> dict[str, list[dict]]:
    """Reconstrói índice a partir de arquivos em output/ (compatibilidade)."""
    lead_map = {normalize_domain(l.get("domain", "")): l for l in (leads or []) if l.get("domain")}
    data = _ler()
    seen_d = {d.get("domain") for d in data["diagnoses"]}
    seen_p = {p.get("domain") for p in data["prototypes"]}

    diag_root = OUTPUT_DIR / "diagnoses"
    if diag_root.exists():
        for ddir in diag_root.iterdir():
            if not ddir.is_dir():
                continue
            domain = ddir.name.replace("_", ".")
            if domain in seen_d:
                continue
            if not (ddir / "diagnostico.md").exists():
                continue
            lead = lead_map.get(domain, {})
            register_diagnosis(domain, lead, {
                "markdown": str(ddir / "diagnostico.md"),
                "html": str(ddir / "diagnostico.html") if (ddir / "diagnostico.html").exists() else "",
            })
            seen_d.add(domain)

    sites_root = OUTPUT_DIR / "sites"
    if sites_root.exists():
        for slug_dir in sites_root.iterdir():
            proto = slug_dir / "prototype" / "index.html"
            if not proto.exists():
                continue
            domain = slug_dir.name.replace("_", ".")
            if domain in seen_p:
                continue
            lead = lead_map.get(domain, {})
            meta = {}
            meta_path = slug_dir / "prototype" / "prototype.meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            register_prototype(
                domain, lead,
                output_path=str(proto),
                variation=meta.get("variation", ""),
                quality_report=meta.get("quality"),
            )
            seen_p.add(domain)

    return _ler()


def _enrich_artifact(item: dict, artifact_type: str) -> dict:
    """Adiciona flags de existência de arquivo físico."""
    from config import OUTPUT_DIR

    slug = item.get("slug") or domain_slug(item.get("domain", ""))
    if artifact_type == "diagnosis":
        html_path = OUTPUT_DIR / "diagnoses" / slug / "diagnostico.html"
        md_path = OUTPUT_DIR / "diagnoses" / slug / "diagnostico.md"
        exists = html_path.exists() or md_path.exists()
    else:
        html_path = OUTPUT_DIR / "sites" / slug / "prototype" / "index.html"
        exists = html_path.exists()
    item["file_exists"] = exists
    if not exists:
        item["open_error"] = "Arquivo não encontrado no servidor. Gere novamente pelo workspace do lead."
    return item


def list_diagnoses(leads: list[dict] | None = None) -> list[dict]:
    data = scan_filesystem(leads)
    lead_map = {normalize_domain(l.get("domain", "")): l for l in (leads or [])}
    out = []
    for item in data["diagnoses"]:
        lead = lead_map.get(item.get("domain", ""), {})
        out.append(_enrich_artifact({
            **item,
            "status": lead.get("crm_status") or item.get("status", "new"),
            "score": lead.get("score") or lead.get("opportunity_score") or item.get("score", 0),
            "business_name": lead.get("nome") or item.get("business_name", ""),
            "icp_id": lead.get("icp_id") or item.get("icp_id", "odontologia"),
        }, "diagnosis"))
    return out


def list_prototypes(leads: list[dict] | None = None) -> list[dict]:
    data = scan_filesystem(leads)
    lead_map = {normalize_domain(l.get("domain", "")): l for l in (leads or [])}
    out = []
    for item in data["prototypes"]:
        lead = lead_map.get(item.get("domain", ""), {})
        out.append(_enrich_artifact({
            **item,
            "status": lead.get("crm_status") or item.get("status", "new"),
            "score": lead.get("score") or lead.get("opportunity_score") or item.get("score", 0),
            "business_name": lead.get("nome") or item.get("business_name", ""),
            "icp_id": lead.get("icp_id") or item.get("icp_id", "odontologia"),
        }, "prototype"))
    return out
