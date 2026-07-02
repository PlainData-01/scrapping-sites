"""Carregador de ICPs (Ideal Customer Profile) a partir de arquivos YAML."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

ICPS_DIR = Path(__file__).resolve().parent.parent / "config" / "icps"
DEFAULT_ICP_ID = "odontologia"

_FALLBACK_ICP: dict[str, Any] = {
    "id": DEFAULT_ICP_ID,
    "name": "Clínicas odontológicas",
    "description": "Clínicas odontológicas com potencial para melhorar captação de agendamentos pelo WhatsApp.",
    "target_keywords": ["clínica odontológica", "dentista"],
    "locations": ["Brasília", "Asa Sul", "Asa Norte"],
    "avoid_keywords": ["hospital", "franquia nacional"],
    "positive_signals": {"wix_site": 25, "no_visible_whatsapp": 20},
    "negative_signals": {"no_phone": -20},
    "offer": {
        "type": "Landing page para captação de agendamentos",
        "promise": "aumentar contatos qualificados pelo WhatsApp",
        "recommended_prototype": "odontologia-premium",
    },
}


@dataclass
class ICP:
    id: str
    name: str
    description: str
    target_keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    avoid_keywords: list[str] = field(default_factory=list)
    positive_signals: dict[str, int] = field(default_factory=dict)
    negative_signals: dict[str, int] = field(default_factory=dict)
    offer: dict[str, str] = field(default_factory=dict)

    @property
    def default_query(self) -> str:
        return self.target_keywords[0] if self.target_keywords else self.name

    @property
    def default_location(self) -> str:
        return self.locations[0] if self.locations else "Brasília"

    @property
    def recommended_prototype(self) -> str:
        return self.offer.get("recommended_prototype", "odontologia-premium")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "target_keywords": self.target_keywords,
            "locations": self.locations,
            "avoid_keywords": self.avoid_keywords,
            "positive_signals": self.positive_signals,
            "negative_signals": self.negative_signals,
            "offer": self.offer,
        }


def _dict_to_icp(data: dict[str, Any]) -> ICP:
    return ICP(
        id=str(data.get("id", DEFAULT_ICP_ID)),
        name=str(data.get("name", "")),
        description=str(data.get("description", "")),
        target_keywords=list(data.get("target_keywords") or []),
        locations=list(data.get("locations") or []),
        avoid_keywords=list(data.get("avoid_keywords") or []),
        positive_signals=dict(data.get("positive_signals") or {}),
        negative_signals=dict(data.get("negative_signals") or {}),
        offer=dict(data.get("offer") or {}),
    )


def load_icp(icp_id: str | None = None) -> ICP:
    """Carrega um ICP por id; fallback seguro para odontologia."""
    target_id = (icp_id or DEFAULT_ICP_ID).strip().lower()
    path = ICPS_DIR / f"{target_id}.yaml"
    if not path.exists():
        logger.warning("ICP '%s' não encontrado em %s — usando fallback", target_id, path)
        if target_id != DEFAULT_ICP_ID:
            return load_icp(DEFAULT_ICP_ID)
        return _dict_to_icp(_FALLBACK_ICP)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("YAML inválido")
        return _dict_to_icp(data)
    except Exception as exc:
        logger.error("Erro ao carregar ICP %s: %s", path, exc)
        return _dict_to_icp(_FALLBACK_ICP)


def list_icps() -> list[ICP]:
    """Lista todos os ICPs disponíveis na pasta config/icps/."""
    icps: list[ICP] = []
    if not ICPS_DIR.exists():
        return [_dict_to_icp(_FALLBACK_ICP)]
    for path in sorted(ICPS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                icps.append(_dict_to_icp(data))
        except Exception as exc:
            logger.warning("Ignorando ICP %s: %s", path.name, exc)
    return icps or [_dict_to_icp(_FALLBACK_ICP)]


def should_avoid_lead(icp: ICP, business_name: str, category: str = "") -> tuple[bool, str]:
    """Verifica se o lead deve ser descartado com base em avoid_keywords do ICP."""
    texto = f"{business_name} {category}".lower()
    for kw in icp.avoid_keywords:
        if kw.lower() in texto:
            return True, f"Palavra evitada pelo ICP: '{kw}'"
    return False, ""
