"""Geração do PDF da proposta comercial."""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from config import OUTPUT_DIR, SiteData

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

LIST_VAR_ITEM_KEYS = {
    "current_site_problems": "problem",
    "urgency_points": "point",
    "suggested_improvements": "improvement",
    "proposal_highlights": "highlight",
}

WKHTMLTOPDF_INSTALL_MSG = (
    "wkhtmltopdf não encontrado. Para gerar PDFs no Windows, instale:\n"
    "  https://wkhtmltopdf.org/downloads.html\n"
    "  Após instalar, adicione ao PATH ou reinicie o terminal."
)


def _render_for_loops(content: str, context: dict) -> str:
    """Processa blocos {% for item in list_var %}...{% endfor %}."""
    pattern = r"\{% for \w+ in (\w+) %\}(.*?)\{% endfor %\}"

    def replace_loop(match: re.Match) -> str:
        var_name = match.group(1)
        item_template = match.group(2)
        items = context.get(var_name, [])
        if not isinstance(items, list):
            return ""

        item_key = LIST_VAR_ITEM_KEYS.get(var_name, "item")
        rendered = ""
        for item in items:
            block = item_template.replace("{{ " + item_key + " }}", str(item))
            rendered += block
        return rendered

    return re.sub(pattern, replace_loop, content, flags=re.DOTALL)


def _render_conditionals(content: str, context: dict) -> str:
    """Processa blocos {% if var %}...{% endif %}."""
    pattern = r"\{% if (\w+) %\}(.*?)\{% endif %\}"

    def replace_if(match: re.Match) -> str:
        var_name = match.group(1)
        body = match.group(2)
        value = context.get(var_name, "")
        if value:
            return body
        return ""

    return re.sub(pattern, replace_if, content, flags=re.DOTALL)


def _render_template(template_path: Path, context: dict) -> str:
    """Renderiza template HTML substituindo placeholders e blocos de controle."""
    content = template_path.read_text(encoding="utf-8")

    content = _render_for_loops(content, context)
    content = _render_conditionals(content, context)

    for key, value in context.items():
        if isinstance(value, list):
            continue
        content = content.replace("{{ " + key + " }}", str(value or ""))

    return content


def _get_home_screenshot(site_data: SiteData) -> str:
    """Retorna caminho do screenshot da home page."""
    for page in site_data.pages:
        if page.get("page_type") == "home" and page.get("screenshot_path"):
            return page["screenshot_path"]
    for path in site_data.screenshots.values():
        return path
    for page in site_data.pages:
        if page.get("screenshot_path"):
            return page["screenshot_path"]
    return ""


def _try_pdfkit(html_content: str, pdf_path: Path) -> bool:
    """Tenta gerar PDF via pdfkit + wkhtmltopdf."""
    try:
        import pdfkit
        options = {
            "page-size": "A4",
            "encoding": "UTF-8",
            "margin-top": "15mm",
            "margin-bottom": "15mm",
            "margin-left": "15mm",
            "margin-right": "15mm",
            "enable-local-file-access": None,
        }
        pdfkit.from_string(
            html_content,
            str(pdf_path),
            options=options,
        )
        return True
    except OSError:
        print(f"\nAVISO: {WKHTMLTOPDF_INSTALL_MSG}\n", file=sys.stderr)
        return False
    except Exception as exc:
        logger.debug("pdfkit falhou: %s", exc)
        return False


def _try_weasyprint(html_content: str, pdf_path: Path) -> bool:
    """Tenta gerar PDF via WeasyPrint como fallback."""
    try:
        from weasyprint import HTML
        HTML(string=html_content, base_url=str(TEMPLATES_DIR)).write_pdf(str(pdf_path))
        return True
    except (ImportError, OSError) as exc:
        logger.debug("WeasyPrint indisponível: %s", exc)
        return False
    except Exception as exc:
        logger.debug("WeasyPrint falhou: %s", exc)
        return False


def _save_html_fallback(html_content: str, domain_safe: str, date_file: str) -> str:
    """Salva HTML quando nenhum gerador de PDF está disponível."""
    html_fallback = OUTPUT_DIR / f"{domain_safe}_{date_file}.html"
    html_fallback.write_text(html_content, encoding="utf-8")
    logger.info("HTML fallback salvo: %s", html_fallback)
    return str(html_fallback)


def generate_proposal_pdf(analysis: dict, site_data: SiteData) -> str:
    """
    Gera PDF da proposta a partir do template HTML.

    Tenta pdfkit (wkhtmltopdf) primeiro, depois WeasyPrint, depois HTML.
    Retorna caminho do arquivo gerado.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%d/%m/%Y")
    domain_safe = site_data.domain.replace(".", "_")
    date_file = datetime.now().strftime("%Y%m%d")
    pdf_filename = f"{domain_safe}_{date_file}.pdf"
    pdf_path = OUTPUT_DIR / pdf_filename

    screenshot = _get_home_screenshot(site_data)
    screenshot_uri = Path(screenshot).resolve().as_posix() if screenshot else ""

    context = {
        "business_name": analysis.get("business_name", site_data.domain),
        "domain": site_data.domain,
        "date": date_str,
        "business_description": analysis.get("business_description", ""),
        "screenshot_path": screenshot_uri,
        "current_site_problems": analysis.get("current_site_problems", []),
        "urgency_points": analysis.get("urgency_points", []),
        "suggested_improvements": analysis.get("suggested_improvements", []),
        "proposal_highlights": analysis.get("proposal_highlights", []),
        "estimated_page_count": analysis.get("estimated_page_count", 5),
    }

    template_path = TEMPLATES_DIR / "proposal_template.html"
    html_content = _render_template(template_path, context)

    if _try_pdfkit(html_content, pdf_path):
        logger.info("PDF gerado via pdfkit: %s", pdf_path)
        return str(pdf_path)

    if _try_weasyprint(html_content, pdf_path):
        logger.info("PDF gerado via WeasyPrint: %s", pdf_path)
        return str(pdf_path)

    logger.warning("Nenhum gerador de PDF disponível — salvando HTML")
    return _save_html_fallback(html_content, domain_safe, date_file)
