"""Orquestrador principal do agente de scraping e prospecção."""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
from urllib.parse import urlparse

from tqdm import tqdm

from config import (
    ANTHROPIC_API_KEY,
    MAX_CONCURRENT_SCRAPERS,
    MAX_PAGES_PER_SITE,
    OUTPUT_DIR,
    SiteData,
    ensure_directories,
)
from crawler.assets import download_assets
from crawler.discover import get_all_pages, priorizar_paginas_prospeccao
from crawler.scraper import close_browser, scrape_page
from output.briefing_export import generate_briefing, _enrich_known_contacts
from output.email_writer import generate_prospecting_email
from output.proposal import generate_proposal_pdf
from output.site_builder import _check_claude_code_available, build_site
from parser.ai_analyzer import analyze_site, generate_proposal_text
from parser.html_parser import parse_page_data
from storage.database import init_database, save_site_data, site_already_crawled

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent")


def check_dependencies() -> None:
    """Verifica dependências externas e avisa o que falta."""
    missing = []
    if not _check_claude_code_available():
        missing.append(
            "Claude Code CLI não encontrado. "
            "Instale com: npm install -g @anthropic-ai/claude-code\n"
            "  (A automação completa de criação de site não funcionará sem isso —\n"
            "   o agente vai salvar o prompt em .md para uso manual.)"
        )
    if not shutil.which("npm"):
        missing.append("npm não encontrado. Instale Node.js: https://nodejs.org")

    if missing:
        print("\n⚠️  AVISOS DE DEPENDÊNCIAS:")
        for m in missing:
            print(f"   - {m}")
        print()


def validate_api_key() -> None:
    """Garante que a API key da Anthropic está configurada."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-..."):
        print(
            "ERRO: Configure sua ANTHROPIC_API_KEY no arquivo .env antes de continuar",
            file=sys.stderr,
        )
        sys.exit(1)


def validate_url(url: str) -> str:
    """Valida e normaliza a URL de entrada."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"URL inválida: {url}")
    return url


async def scrape_pages_parallel(
    urls: list[str],
    max_workers: int = MAX_CONCURRENT_SCRAPERS,
    fast_mode: bool = False,
) -> list[dict]:
    """Scrapeia páginas em paralelo com limite de workers."""
    semaphore = asyncio.Semaphore(max_workers)
    results: list[dict] = []

    async def _scrape_one(url: str) -> dict | None:
        async with semaphore:
            return await scrape_page(url, fast_mode=fast_mode)

    tasks = [_scrape_one(url) for url in urls]
    for coro in tqdm(
        asyncio.as_completed(tasks),
        total=len(tasks),
        desc="Scraping páginas",
        unit="página",
    ):
        result = await coro
        if result:
            results.append(result)

    return results


def _merge_contacts(site_data: SiteData) -> None:
    """Consolida contatos de todas as páginas."""
    all_emails: set[str] = set()
    all_phones: set[str] = set()
    all_addresses: set[str] = set()
    all_whatsapp: set[str] = set()
    all_telefones: list[str] = []
    telefone: str = ""
    instagram: str = ""
    facebook: str = ""
    cro: str = ""
    endereco: str = ""

    for page in site_data.pages:
        contacts = page.get("contacts", {})
        all_emails.update(contacts.get("emails", []))
        all_phones.update(contacts.get("phones", []))
        all_addresses.update(contacts.get("addresses", []))
        all_telefones.extend(contacts.get("telefones", []))
        wa = contacts.get("whatsapp", "")
        if isinstance(wa, str) and wa:
            all_whatsapp.add(wa)
        elif isinstance(wa, list):
            all_whatsapp.update(wa)
        if not telefone and contacts.get("telefone"):
            telefone = contacts["telefone"]
        if not telefone and contacts.get("telefones"):
            telefone = contacts["telefones"][0]
        if not instagram and contacts.get("instagram"):
            instagram = contacts["instagram"]
        if not facebook and contacts.get("facebook"):
            facebook = contacts["facebook"]
        if not cro and contacts.get("cro"):
            cro = contacts["cro"]
        if not endereco and contacts.get("endereco"):
            endereco = contacts["endereco"]

    unique_tels = list(dict.fromkeys(
        t.strip() for t in (all_telefones + list(all_phones)) if t.strip()
    ))

    merged: dict = {
        "emails": list(all_emails),
        "phones": unique_tels[:5],
        "telefones": unique_tels[:5],
        "addresses": list(all_addresses),
        "whatsapp": next(iter(all_whatsapp), ""),
        "telefone": telefone or (unique_tels[0] if unique_tels else ""),
        "instagram": instagram,
        "facebook": facebook,
        "cro": cro,
    }
    if endereco:
        merged["endereco"] = endereco
    elif merged["addresses"]:
        merged["endereco"] = merged["addresses"][0]

    site_data.contacts = merged
    _enrich_known_contacts(site_data)


def _merge_seo_issues(site_data: SiteData) -> None:
    """Consolida problemas de SEO de todas as páginas."""
    issues: list[str] = []
    for page in site_data.pages:
        for issue in page.get("seo_issues", []):
            page_url = page.get("url", "")
            issues.append(f"[{page_url}] {issue}")
    site_data.seo_issues = issues


def _ensure_seo_issues(site_data: SiteData) -> None:
    """Garante seo_issues preenchido — re-parseia HTML se necessário."""
    from parser.html_parser import parse_page_data

    for page in site_data.pages:
        if page.get("seo_issues"):
            continue
        html = page.get("html", "")
        if not html:
            continue
        parsed = parse_page_data(html, page.get("url", site_data.url))
        page["seo_issues"] = parsed.get("seo_issues", [])

    _merge_seo_issues(site_data)


def _merge_colors_fonts(site_data: SiteData) -> None:
    """Consolida cores e fontes detectadas."""
    from collections import Counter

    color_counter: Counter = Counter()
    font_set: set[str] = set()

    for page in site_data.pages:
        for color in page.get("colors", []):
            color_counter[color] += 1
        for font in page.get("fonts", []):
            font_set.add(font)

    site_data.colors = [c for c, _ in color_counter.most_common(5)]
    site_data.fonts = list(font_set)[:5]


async def run_agent(
    url: str,
    output_dir: str | None = None,
    max_pages: int | None = None,
    skip_cache: bool = False,
    interactive: bool = True,
    prospect_mode: bool = False,
) -> SiteData:
    """Executa o fluxo completo do agente."""
    if output_dir:
        import config
        from pathlib import Path
        config.OUTPUT_DIR = Path(output_dir)

    ensure_directories()
    await init_database()

    url = validate_url(url)
    limit = max_pages or MAX_PAGES_PER_SITE
    logger.info("Iniciando agente para %s (max %d páginas)", url, limit)

    site_data = SiteData(url=url)

    if not skip_cache:
        cached, cache_data = await site_already_crawled(url)
        if cached and cache_data:
            use_cache = False
            if interactive and sys.stdin.isatty():
                answer = input(
                    f"Site já rastreado recentemente ({len(cache_data.get('pages', []))} páginas). "
                    "Usar cache? [s/N]: "
                ).strip().lower()
                use_cache = answer in ("s", "sim", "y", "yes")
            else:
                use_cache = True

            if use_cache:
                logger.info("Usando dados do cache")
                site_data.pages = cache_data.get("pages", [])
                site_data.contacts = cache_data.get("contacts", {})
                site_data.seo_issues = cache_data.get("seo_issues", [])
                site_data.colors = cache_data.get("colors", [])
                site_data.fonts = cache_data.get("fonts", [])
                site_data.screenshots = cache_data.get("screenshots", {})
                site_data.analysis = cache_data.get("analysis")
                site_data.proposal_pdf_path = cache_data.get("proposal_pdf_path")
                site_data.email_content = cache_data.get("email_content")
                site_data.briefing_path = cache_data.get("briefing_path")
                site_data.site_project_path = cache_data.get("site_project_path")
                _ensure_seo_issues(site_data)

                if prospect_mode:
                    if not site_data.analysis:
                        try:
                            site_data.analysis = await analyze_site(
                                site_data, modo_prospeccao=True,
                            )
                        except Exception as exc:
                            logger.warning("Análise IA falhou no cache: %s", exc)
                    await save_site_data(site_data)
                    _print_summary(site_data)
                    return site_data

                if site_data.analysis:
                    logger.info("Gerando briefing a partir do cache...")
                    site_data.briefing_path = await generate_briefing(
                        site_data, site_data.analysis
                    )
                    logger.info(
                        "Verificando briefing_path antes da Etapa 10 (cache): %r",
                        site_data.briefing_path,
                    )
                    if site_data.briefing_path:
                        logger.info("Etapa 10/11: Construindo site Next.js via Claude Code...")
                        try:
                            project_path, post_status = await build_site(
                                site_data, site_data.analysis, site_data.briefing_path
                            )
                            site_data.site_project_path = project_path
                            _print_site_build_status(project_path, post_status)
                        except Exception as exc:
                            logger.error(
                                "Falha ao construir site (cache): %s", exc, exc_info=True
                            )
                    else:
                        logger.warning(
                            "Etapa 10/11 PULADA (cache) — briefing_path vazio: %r",
                            site_data.briefing_path,
                        )
                _print_summary(site_data)
                return site_data

    logger.info("Etapa 1/11: Descobrindo páginas...")
    fast_mode = limit <= 10
    pages_urls = await get_all_pages(url, max_pages=limit)
    if not pages_urls:
        pages_urls = [url]
    if fast_mode:
        pages_urls = priorizar_paginas_prospeccao(pages_urls, max_pages=limit)
        logger.info("Modo rápido: %d páginas priorizadas para prospecção", len(pages_urls))
    logger.info("Encontradas %d páginas", len(pages_urls))

    logger.info("Etapa 2/11: Scrapeando páginas...")
    if fast_mode:
        logger.info("Modo rápido de scraping ativado (prospecção)")
    raw_pages = await scrape_pages_parallel(pages_urls, fast_mode=fast_mode)
    await close_browser()

    logger.info("Etapa 3/11: Baixando assets...")
    all_image_urls: list[str] = []
    for page in raw_pages:
        for img in page.get("images", []):
            all_image_urls.append(img["src"])

    assets_dir = OUTPUT_DIR / "assets" / site_data.domain.replace(".", "_")
    asset_mapping = await download_assets(all_image_urls, assets_dir)
    site_data.assets = [
        {"url": k, "local_path": v} for k, v in asset_mapping.items()
    ]

    logger.info("Etapa 4/11: Parseando HTML...")
    for raw in raw_pages:
        parsed = parse_page_data(raw.get("html", ""), raw["url"])
        parsed["texts"] = raw.get("texts", [])
        parsed["images"] = raw.get("images", [])
        parsed["meta"] = raw.get("meta", {})
        parsed["colors"] = raw.get("colors", [])
        parsed["fonts"] = raw.get("fonts", [])
        parsed["screenshot_path"] = raw.get("screenshot_path", "")
        parsed["html"] = raw.get("html", "")

        scraper_contacts = raw.get("contacts", {})
        parsed_contacts = parsed.get("contacts", {})

        telefones: list[str] = []
        for src in (scraper_contacts, parsed_contacts):
            telefones.extend(src.get("telefones", []))
            telefones.extend(src.get("phones", []))
            if src.get("telefone"):
                telefones.append(src["telefone"])

        whatsapp = scraper_contacts.get("whatsapp") or parsed_contacts.get("whatsapp", "")
        unique_tels = list(dict.fromkeys(t.strip() for t in telefones if t.strip()))

        parsed["contacts"] = {
            "emails": list(set(
                scraper_contacts.get("emails", []) + parsed_contacts.get("emails", [])
            )),
            "phones": unique_tels[:5],
            "telefones": unique_tels[:5],
            "addresses": list(set(
                scraper_contacts.get("addresses", []) + parsed_contacts.get("addresses", [])
            )),
            "whatsapp": whatsapp,
            "telefone": unique_tels[0] if unique_tels else "",
        }

        site_data.pages.append(parsed)
        if parsed.get("screenshot_path"):
            site_data.screenshots[parsed["url"]] = parsed["screenshot_path"]

    _merge_contacts(site_data)
    _ensure_seo_issues(site_data)
    _merge_colors_fonts(site_data)

    logger.info("Etapa 5/11: Analisando com Claude API...")
    modo_prospeccao = prospect_mode or limit <= 10
    try:
        analysis = await analyze_site(site_data, modo_prospeccao=modo_prospeccao)
        site_data.analysis = analysis
    except Exception as exc:
        logger.warning("Análise IA falhou, continuando sem IA: %s", exc)
        site_data.analysis = None

    if site_data.analysis:
        if not prospect_mode:
            logger.info("Etapa 6/11: Gerando texto da proposta...")
            proposal_text = generate_proposal_text(site_data.analysis, site_data)
            logger.debug("Proposta (%d chars): %s...", len(proposal_text), proposal_text[:100])

            logger.info("Etapa 7/11: Gerando PDF...")
            try:
                pdf_path = generate_proposal_pdf(site_data.analysis, site_data)
                site_data.proposal_pdf_path = pdf_path
            except Exception as exc:
                logger.error("Falha ao gerar PDF: %s", exc)

        logger.info("Etapa 8/11: Gerando email de prospecção...")
        site_data.email_content = generate_prospecting_email(
            site_data.analysis, site_data
        )
    else:
        logger.warning("Pulando geração de proposta/email (sem análise)")

    analysis_for_briefing = site_data.analysis or {}

    if prospect_mode:
        logger.info("Modo prospecção: pulando briefing e construção de site")
        logger.info("Salvando no banco de dados...")
        await save_site_data(site_data)
        _print_summary(site_data)
        return site_data

    logger.info("Etapa 9/11: Gerando briefing para IA construtora...")
    try:
        briefing_path = await generate_briefing(site_data, analysis_for_briefing)
        site_data.briefing_path = briefing_path
        print(f"\n[OK] Briefing gerado: {briefing_path}")
        print("   -> Cole o conteúdo da seção 9 no Lovable/V0/Bolt.new")
        domain_assets = site_data.domain.replace(".", "_")
        print(f"   -> Assets salvos em: output/briefings/{domain_assets}/assets/")
    except Exception as exc:
        logger.error("Falha ao gerar briefing: %s", exc)

    logger.info(
        "Verificando briefing_path antes da Etapa 10: %r",
        site_data.briefing_path,
    )
    if site_data.briefing_path:
        logger.info("Etapa 10/11: Construindo site Next.js via Claude Code...")
        try:
            project_path, post_status = await build_site(
                site_data, analysis_for_briefing, site_data.briefing_path
            )
            site_data.site_project_path = project_path
            _print_site_build_status(project_path, post_status)
        except Exception as exc:
            logger.error("Falha ao construir site: %s", exc, exc_info=True)
    else:
        logger.warning(
            "Etapa 10/11 PULADA — briefing_path está vazio ou None: %r",
            site_data.briefing_path,
        )

    logger.info("Etapa 11/11: Salvando no banco de dados...")
    await save_site_data(site_data)

    _print_summary(site_data)
    return site_data


def _configure_event_loop() -> None:
    """Reservado para ajustes de event loop por plataforma."""
    return


async def _run_agent_safe(**kwargs) -> SiteData:
    try:
        return await run_agent(**kwargs)
    finally:
        try:
            await close_browser()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Erro ao fechar browser: %s", exc)
        try:
            await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            pass


def _print_site_build_status(project_path: str, post_status: dict) -> None:
    """Imprime status da geração automática do site Next.js."""
    if not project_path:
        return
    print(f"\n🚀 Site Next.js gerado em: {project_path}")
    if post_status.get("build_ok"):
        print("   ✅ Build validado com sucesso")
        print(f"   → cd {project_path} && npm run dev")
    elif post_status.get("npm_install"):
        print("   ⚠️ Dependências instaladas, mas build apresentou erros")
        print(f"   → Revise manualmente: cd {project_path}")
    else:
        print(f"   ⚠️ Verifique manualmente o projeto em: {project_path}")


def _print_summary(site_data: SiteData) -> None:
    """Imprime resumo final no terminal."""
    print("\n" + "=" * 60)
    print("  RESUMO DO AGENTE DE SCRAPING")
    print("=" * 60)
    print(f"  Domínio:        {site_data.domain}")
    print(f"  Páginas:        {len(site_data.pages)}")
    print(f"  Assets:         {len(site_data.assets)}")
    whatsapp = site_data.contacts.get("whatsapp", "")
    telefone = site_data.contacts.get("telefone", "")
    print(f"  Contatos:       {len(site_data.contacts.get('emails', []))} emails, "
          f"{len(site_data.contacts.get('phones', []))} telefones"
          + (f", WhatsApp: {whatsapp}" if whatsapp else "")
          + (f", tel: {telefone}" if telefone else ""))

    if site_data.seo_issues:
        print(f"  Problemas SEO:  {len(site_data.seo_issues)}")
        for issue in site_data.seo_issues[:5]:
            print(f"    - {issue}")
        if len(site_data.seo_issues) > 5:
            print(f"    ... e mais {len(site_data.seo_issues) - 5}")

    if site_data.analysis:
        print(f"  Negócio:        {site_data.analysis.get('business_name', 'N/A')}")
        print(f"  Tipo:           {site_data.analysis.get('business_type', 'N/A')}")

    if site_data.proposal_pdf_path:
        print(f"  PDF:            {site_data.proposal_pdf_path}")

    if site_data.briefing_path:
        print(f"  Briefing:       {site_data.briefing_path}")

    if site_data.site_project_path:
        print(f"  Site Next.js:   {site_data.site_project_path}")

    if site_data.email_content:
        print(f"  Email assunto:  {site_data.email_content.get('subject', 'N/A')}")
        print("-" * 60)
        print(site_data.email_content.get("body_text", ""))

    print("=" * 60 + "\n")


def main() -> None:
    """Ponto de entrada CLI."""
    parser = argparse.ArgumentParser(
        description="Agente de scraping e prospecção de clientes"
    )
    parser.add_argument(
        "--url", required=True, help="URL do site do cliente em potencial"
    )
    parser.add_argument(
        "--output-dir", default=None, help="Diretório de saída (default: ./output)"
    )
    parser.add_argument(
        "--max-pages", type=int, default=None, help="Máximo de páginas a rastrear"
    )
    parser.add_argument(
        "--skip-cache", action="store_true", help="Forçar re-crawl ignorando cache"
    )

    args = parser.parse_args()

    check_dependencies()
    validate_api_key()

    try:
        _configure_event_loop()
        asyncio.run(
            _run_agent_safe(
                url=args.url,
                output_dir=args.output_dir,
                max_pages=args.max_pages,
                skip_cache=args.skip_cache,
            )
        )
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário")
        sys.exit(1)
    except Exception as exc:
        logger.error("Erro fatal: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
