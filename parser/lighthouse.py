"""Módulo opcional de análise PageSpeed/Lighthouse."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PAGESPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def lighthouse_enabled() -> bool:
    return os.getenv("ENABLE_LIGHTHOUSE", "false").strip().lower() in ("true", "1", "yes")


async def analyze_pagespeed(url: str) -> dict[str, Any] | None:
    """
    Obtém métricas via PageSpeed Insights API.
    Retorna None se desabilitado ou sem API key.
    """
    if not lighthouse_enabled():
        return None

    api_key = os.getenv("PAGESPEED_API_KEY", "").strip()
    if not api_key:
        logger.debug("Lighthouse habilitado mas PAGESPEED_API_KEY ausente")
        return None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                PAGESPEED_URL,
                params={
                    "url": url,
                    "key": api_key,
                    "strategy": "mobile",
                    "category": ["performance", "seo", "accessibility", "best-practices"],
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("PageSpeed falhou para %s: %s", url, exc)
        return None

    categories = data.get("lighthouseResult", {}).get("categories", {})
    audits = data.get("lighthouseResult", {}).get("audits", {})

    scores = {
        name: round(cat.get("score", 0) * 100)
        for name, cat in categories.items()
        if isinstance(cat, dict)
    }

    issues: list[str] = []
    for audit_id, audit in audits.items():
        if not isinstance(audit, dict):
            continue
        score = audit.get("score")
        if score is not None and score < 0.5:
            title = audit.get("title", audit_id)
            issues.append(title)

    return {
        "performance_mobile": scores.get("performance", 0),
        "seo": scores.get("seo", 0),
        "accessibility": scores.get("accessibility", 0),
        "best_practices": scores.get("best-practices", 0),
        "issues": issues[:8],
        "source": "pagespeed",
    }
