"""Camada abstrata de geração de sites/protótipos."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR, SiteData

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "prototypes"


class GeneratorMode(str, Enum):
    TEMPLATE = "template"
    CLAUDE_CODE = "claude_code"
    PROMPT_ONLY = "prompt_only"


@dataclass
class SiteGeneratorInput:
    site_data: SiteData
    analysis: dict[str, Any]
    lead: dict[str, Any] = field(default_factory=dict)
    icp_id: str = "odontologia"
    template_id: str = ""
    variation: str = ""
    briefing_path: str | None = None


@dataclass
class SiteGeneratorResult:
    mode: str
    success: bool
    output_path: str = ""
    prompt_path: str = ""
    preview_url: str = ""
    message: str = ""
    error: str = ""


def default_mode() -> GeneratorMode:
    raw = os.getenv("DEFAULT_SITE_GENERATOR_MODE", "template").strip().lower()
    try:
        return GeneratorMode(raw)
    except ValueError:
        return GeneratorMode.TEMPLATE


class SiteGenerator:
    """Gera protótipos/sites em múltiplos modos."""

    async def generate(
        self,
        input_data: SiteGeneratorInput,
        mode: GeneratorMode | str | None = None,
    ) -> SiteGeneratorResult:
        resolved = self._resolve_mode(mode)
        logger.info("SiteGenerator: modo=%s domain=%s", resolved.value, input_data.site_data.domain)

        if resolved == GeneratorMode.TEMPLATE:
            return await self._generate_template(input_data)
        if resolved == GeneratorMode.CLAUDE_CODE:
            return await self._generate_claude_code(input_data)
        return await self._generate_prompt_only(input_data)

    def _resolve_mode(self, mode: GeneratorMode | str | None) -> GeneratorMode:
        if mode is None:
            return default_mode()
        if isinstance(mode, GeneratorMode):
            return mode
        try:
            return GeneratorMode(str(mode).strip().lower())
        except ValueError:
            return default_mode()

    async def _generate_template(self, input_data: SiteGeneratorInput) -> SiteGeneratorResult:
        from output.template_builder import build_from_template

        try:
            result = await build_from_template(input_data)
            return SiteGeneratorResult(
                mode=GeneratorMode.TEMPLATE.value,
                success=True,
                output_path=result.get("output_path", ""),
                preview_url=result.get("preview_url", ""),
                message="Protótipo gerado a partir de template.",
            )
        except Exception as exc:
            logger.exception("Falha no modo template: %s", exc)
            return SiteGeneratorResult(
                mode=GeneratorMode.TEMPLATE.value,
                success=False,
                error=str(exc),
                message="Falha no template — tente prompt_only ou claude_code.",
            )

    async def _generate_claude_code(self, input_data: SiteGeneratorInput) -> SiteGeneratorResult:
        from output.site_builder import build_site, _check_claude_code_available

        briefing = input_data.briefing_path
        if not briefing:
            from output.briefing_export import generate_briefing
            briefing = await generate_briefing(input_data.site_data, input_data.analysis)

        if not _check_claude_code_available():
            prompt_result = await self._generate_prompt_only(input_data)
            prompt_result.message = (
                "Claude Code não encontrado — prompt salvo para uso manual."
            )
            return prompt_result

        try:
            project_path = await build_site(
                input_data.site_data,
                input_data.analysis,
                briefing,
            )
            slug = input_data.site_data.domain.replace(".", "_")
            prompt_path = str(OUTPUT_DIR / "sites" / f"{slug}_cursor_prompt.md")
            return SiteGeneratorResult(
                mode=GeneratorMode.CLAUDE_CODE.value,
                success=bool(project_path),
                output_path=project_path or "",
                prompt_path=prompt_path,
                message="Site gerado via Claude Code CLI.",
            )
        except Exception as exc:
            logger.exception("Falha no modo claude_code: %s", exc)
            return SiteGeneratorResult(
                mode=GeneratorMode.CLAUDE_CODE.value,
                success=False,
                error=str(exc),
            )

    async def _generate_prompt_only(self, input_data: SiteGeneratorInput) -> SiteGeneratorResult:
        from output.site_builder import _build_reconstruction_prompt, _extract_section_9

        site_data = input_data.site_data
        analysis = input_data.analysis
        slug = site_data.domain.replace(".", "_")
        project_dir = OUTPUT_DIR / "sites" / slug
        project_dir.mkdir(parents=True, exist_ok=True)

        briefing_content = ""
        if input_data.briefing_path and Path(input_data.briefing_path).exists():
            briefing_content = Path(input_data.briefing_path).read_text(encoding="utf-8")
        section_9 = _extract_section_9(briefing_content) if briefing_content else ""

        prompt = _build_reconstruction_prompt(site_data, analysis, section_9)
        prompt_path = OUTPUT_DIR / "sites" / f"{slug}_cursor_prompt.md"
        build_path = project_dir / "BUILD_PROMPT.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        build_path.write_text(prompt, encoding="utf-8")

        return SiteGeneratorResult(
            mode=GeneratorMode.PROMPT_ONLY.value,
            success=True,
            prompt_path=str(prompt_path),
            output_path=str(project_dir),
            message="Prompt estruturado salvo para uso em Cursor, v0 ou Framer.",
        )


async def generate_site(
    site_data: SiteData,
    analysis: dict[str, Any],
    lead: dict | None = None,
    mode: str | None = None,
    **kwargs: Any,
) -> SiteGeneratorResult:
    """Atalho funcional para geração de site/protótipo."""
    gen = SiteGenerator()
    inp = SiteGeneratorInput(
        site_data=site_data,
        analysis=analysis,
        lead=lead or {},
        icp_id=kwargs.get("icp_id", "odontologia"),
        template_id=kwargs.get("template_id", ""),
        variation=kwargs.get("variation", ""),
        briefing_path=kwargs.get("briefing_path"),
    )
    return await gen.generate(inp, mode=mode)
