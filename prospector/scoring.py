"""Scoring explicável baseado em ICP e sinais comerciais."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prospector.icp_loader import ICP


@dataclass
class ScoreResult:
    opportunity_score: int
    score_reasons: list[str] = field(default_factory=list)
    main_pain: str = ""
    commercial_angle: str = ""
    suggested_offer: str = ""
    score_detalhes: dict[str, Any] = field(default_factory=dict)


def _clamp(score: int) -> int:
    return max(0, min(100, score))


def _platform_signal(plataforma: str) -> str | None:
    mapping = {
        "wix": "wix_site",
        "wordpress": "wordpress_site",
        "elementor": "wordpress_site",
        "webflow": "very_modern_site",
        "shopify": "very_modern_site",
    }
    return mapping.get(plataforma.lower())


def compute_score(
    icp: ICP,
    *,
    plataforma: str = "",
    avaliacao: float = 0.0,
    total_avaliacoes: int = 0,
    has_website: bool = True,
    has_whatsapp: bool = False,
    has_visible_cta: bool = False,
    has_contact_form: bool = False,
    has_meta_pixel: bool = False,
    has_gtm: bool = False,
    has_service_pages: bool = False,
    has_social_proof: bool = False,
    old_visual_site: bool = False,
    weak_mobile_cta: bool = False,
    endereco: str = "",
    has_phone: bool = False,
    commercial_issues: list[str] | None = None,
) -> ScoreResult:
    """Calcula score 0-100 com razões explicáveis."""
    score = 50  # base neutra
    reasons: list[str] = []
    detalhes: dict[str, Any] = {}
    pos = icp.positive_signals
    neg = icp.negative_signals

    def add(signal: str, pts: int, reason: str) -> None:
        nonlocal score
        score += pts
        reasons.append(reason)
        detalhes[signal] = {"pontos": pts, "motivo": reason}

    # Plataforma
    plat_signal = _platform_signal(plataforma)
    if plat_signal and plat_signal in pos:
        pts = pos[plat_signal]
        label = plataforma.title() if plataforma else "Plataforma"
        add(plat_signal, pts, f"Site detectado em {label}, o que pode indicar oportunidade de modernização.")

    if plataforma.lower() == "webflow" and "very_modern_site" in neg:
        add("very_modern_site", neg["very_modern_site"], "Site em Webflow — provavelmente bem feito, menor urgência.")

    # Website
    if not has_website and "no_website" in neg:
        add("no_website", neg["no_website"], "Sem site próprio detectado.")
    elif has_website and "website_exists" in pos:
        add("website_exists", pos["website_exists"], "Possui site próprio para análise e melhoria.")

    # WhatsApp / CTA
    if not has_visible_cta and weak_mobile_cta and "weak_mobile_cta" in pos:
        add("weak_mobile_cta", pos["weak_mobile_cta"], "Não foi encontrado CTA claro para WhatsApp acima da dobra.")
    elif not has_whatsapp and "no_visible_whatsapp" in pos:
        add("no_visible_whatsapp", pos["no_visible_whatsapp"], "WhatsApp não visível de forma clara no site.")
    elif has_whatsapp and "whatsapp_found" in pos:
        add("whatsapp_found", pos["whatsapp_found"], "WhatsApp encontrado no site.")

    # Tracking
    if not has_meta_pixel and "no_meta_pixel" in pos:
        add("no_meta_pixel", pos["no_meta_pixel"], "Não foi detectado Meta Pixel.")
    if not has_gtm and "no_gtm" in pos:
        add("no_gtm", pos["no_gtm"], "Não foi detectado Google Tag Manager.")
    if not has_contact_form and "no_contact_form" in pos:
        add("no_contact_form", pos["no_contact_form"], "Sem formulário de contato visível.")

    # Conteúdo
    if not has_service_pages and "no_service_pages" in pos:
        add("no_service_pages", pos["no_service_pages"], "Poucas ou nenhuma página de serviços/procedimentos.")
    if not has_social_proof and "no_social_proof_on_site" in pos:
        add("no_social_proof_on_site", pos["no_social_proof_on_site"], "Sem prova social ou depoimentos no site.")
    if old_visual_site and "old_visual_site" in pos:
        add("old_visual_site", pos["old_visual_site"], "Site com aparência visual datada ou genérica.")

    # Avaliações Google
    if avaliacao >= 4.5 and "rating_above_4_5" in pos:
        add("rating_above_4_5", pos["rating_above_4_5"], f"Avaliação {avaliacao:.1f}★ no Google — boa reputação.")
    elif avaliacao >= 4.3 and "rating_above_4_3" in pos:
        add("rating_above_4_3", pos["rating_above_4_3"], f"Avaliação {avaliacao:.1f}★ no Google.")
    elif avaliacao > 0 and avaliacao < 3.5 and "low_rating" in neg:
        add("low_rating", neg["low_rating"], f"Avaliação baixa ({avaliacao:.1f}★).")

    if total_avaliacoes >= 100 and "reviews_above_100" in pos:
        add("reviews_above_100", pos["reviews_above_100"], f"Mais de {total_avaliacoes} avaliações — demanda existente.")
    elif total_avaliacoes >= 50 and "reviews_above_50" in pos:
        add("reviews_above_50", pos["reviews_above_50"], f"A empresa tem mais de {total_avaliacoes} avaliações no Google.")
    elif total_avaliacoes >= 30 and "reviews_above_30" in pos:
        add("reviews_above_30", pos["reviews_above_30"], f"{total_avaliacoes} avaliações no Google.")
    elif total_avaliacoes >= 20 and "reviews_above_20" in pos:
        add("reviews_above_20", pos["reviews_above_20"], f"{total_avaliacoes} avaliações no Google.")
    elif total_avaliacoes < 10 and "few_reviews" in neg:
        add("few_reviews", neg["few_reviews"], f"Poucas avaliações ({total_avaliacoes}).")

    # Localização premium
    endereco_lower = endereco.lower()
    for loc in icp.locations:
        if loc.lower() in endereco_lower and "premium_neighborhood" in pos:
            add("premium_neighborhood", pos["premium_neighborhood"], f"Localização em {loc}.")
            break

    # Telefone
    if not has_phone and "no_phone" in neg:
        add("no_phone", neg["no_phone"], "Sem telefone válido para contato.")

    # Issues comerciais extras
    for issue in (commercial_issues or [])[:3]:
        if issue not in reasons:
            reasons.append(issue)

    final_score = _clamp(score)
    offer = icp.offer

    main_pain = _infer_main_pain(reasons, commercial_issues or [])
    commercial_angle = _infer_commercial_angle(avaliacao, total_avaliacoes, reasons, offer)
    suggested = offer.get("type", "Landing page personalizada")

    return ScoreResult(
        opportunity_score=final_score,
        score_reasons=reasons[:8],
        main_pain=main_pain,
        commercial_angle=commercial_angle,
        suggested_offer=suggested,
        score_detalhes=detalhes,
    )


def _infer_main_pain(reasons: list[str], issues: list[str]) -> str:
    for r in reasons:
        if "cta" in r.lower() or "whatsapp" in r.lower():
            return "O site pode estar perdendo agendamentos no celular por falta de CTA claro."
        if "wix" in r.lower() or "modernização" in r.lower():
            return "O site atual pode limitar conversão e credibilidade no mobile."
        if "serviços" in r.lower() or "procedimentos" in r.lower():
            return "Visitantes não encontram claramente os serviços oferecidos."
    if issues:
        return issues[0]
    return "Há oportunidades de melhorar a conversão do site em contatos qualificados."


def _infer_commercial_angle(
    avaliacao: float,
    reviews: int,
    reasons: list[str],
    offer: dict[str, str],
) -> str:
    promise = offer.get("promise", "melhorar a conversão do tráfego")
    if reviews >= 30 and avaliacao >= 4.0:
        return (
            f"A empresa já tem demanda e avaliações, mas pode {promise} com um site mais direto."
        )
    return f"Com ajustes focados no mobile e no WhatsApp, dá para {promise}."
