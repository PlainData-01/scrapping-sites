"""Injeta dados reais do scraping no projeto Next.js gerado."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urlparse

from config import OUTPUT_DIR, SiteData
from output.briefing_export import BRIEFINGS_DIR, _enrich_known_contacts

logger = logging.getLogger(__name__)

# Marcadores de nicho usados na validação de sanidade (cross-contamination).
NICHE_MARKERS: dict[str, list[str]] = {
    "dental": [
        "odontolog",
        "dentista",
        "viviane",
        "draviviane",
        "dra viviane",
        "clínica odontológica",
        "clinica odontologica",
        "ortodont",
        "invisalign",
    ],
    "energy": [
        "gerador",
        "grupos geradores",
        "grupo gerador",
        "energia",
        "genforce",
        "nobreak",
        "geração de energia",
    ],
}

DENTAL_NICHE_CATEGORIES = frozenset({"saude_premium"})
ENERGY_NICHE_CATEGORIES = frozenset({"industrial_b2b"})


def _ts_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _infer_niche(analysis: dict, site_data: SiteData) -> str:
    """Retorna 'dental', 'energy' ou 'generic' com base no analysis e domínio."""
    category = (analysis.get("niche_category") or "").lower()
    if category in DENTAL_NICHE_CATEGORIES:
        return "dental"
    if category in ENERGY_NICHE_CATEGORIES:
        return "energy"

    haystack = " ".join(
        str(analysis.get(k, "")) for k in ("business_name", "business_type", "business_description")
    ).lower()
    haystack += f" {site_data.domain.lower()}"

    dental_score = sum(1 for m in NICHE_MARKERS["dental"] if m in haystack)
    energy_score = sum(1 for m in NICHE_MARKERS["energy"] if m in haystack)

    if dental_score > energy_score and dental_score > 0:
        return "dental"
    if energy_score > dental_score and energy_score > 0:
        return "energy"
    return "generic"


def _keywords_from_context(analysis: dict, site_data: SiteData) -> list[str]:
    keywords: list[str] = []
    for field in ("business_name", "business_type"):
        for word in str(analysis.get(field, "")).lower().split():
            if len(word) > 3:
                keywords.append(word)
    domain_base = site_data.domain.replace("www.", "").split(".")[0]
    if domain_base:
        keywords.append(domain_base)
    return keywords


def _collect_images(site_data: SiteData) -> list[dict]:
    images: list[dict] = []
    seen: set[str] = set()
    for page in site_data.pages:
        for img in page.get("images", []):
            url = img.get("src") or img.get("url", "")
            if not url or url.startswith("data:") or url in seen:
                continue
            seen.add(url)
            images.append({
                "url": url,
                "alt": img.get("alt", ""),
                "page_type": page.get("page_type", ""),
            })
    for asset in site_data.assets:
        url = asset.get("url", "")
        if url and url not in seen:
            seen.add(url)
            images.append({"url": url, "alt": "", "page_type": ""})
    return images


def _pick_image(images: list[dict], *keywords: str) -> str:
    for img in images:
        hay = f"{img.get('url', '')} {img.get('alt', '')}".lower()
        if any(k in hay for k in keywords):
            return img["url"]
    return ""


def _first_content_image(images: list[dict], exclude_logo: bool = True) -> str:
    for img in images:
        url = img["url"].lower()
        if exclude_logo and "logo" in url:
            continue
        if any(ext in url for ext in (".jpg", ".jpeg", ".webp", ".png")):
            if img.get("page_type") in ("home", "sobre", ""):
                return img["url"]
    for img in images:
        url = img["url"].lower()
        if exclude_logo and "logo" in url:
            continue
        if any(ext in url for ext in (".jpg", ".jpeg", ".webp", ".png")):
            return img["url"]
    return ""


def build_image_catalog(site_data: SiteData, analysis: dict | None = None) -> dict[str, str | dict[str, str]]:
    """Monta catálogo de imagens a partir do scraping da execução atual."""
    analysis = analysis or {}
    images = _collect_images(site_data)
    context_kws = _keywords_from_context(analysis, site_data)

    catalog: dict[str, str | dict[str, str]] = {
        "logo": _pick_image(images, "logotipo", "logo"),
        "hero": _pick_image(images, "hero", "banner", "destaque", *context_kws[:3]),
        "about": _pick_image(images, "sobre", "about", "empresa", "equipe", "instala"),
        "porServico": {},
    }

    if not catalog["hero"]:
        catalog["hero"] = _first_content_image(images)
    if not catalog["about"]:
        catalog["about"] = _pick_image(images, "sobre", "about") or str(catalog["hero"])

    por_servico: dict[str, str] = {}
    for page in site_data.pages:
        if page.get("page_type") not in ("servico", "servicos"):
            continue
        url = page.get("url", "")
        slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
        slug = re.sub(r"[^a-z0-9-]", "-", slug).strip("-")
        if not slug or slug in ("servicos", "tratamentos"):
            continue
        page_imgs = page.get("images", [])
        for img in page_imgs:
            img_url = img.get("src") or img.get("url", "")
            if img_url and not img_url.startswith("data:"):
                por_servico[slug] = img_url
                break
        if slug not in por_servico:
            picked = _pick_image(images, slug.replace("-", " "))
            if picked:
                por_servico[slug] = picked

    catalog["porServico"] = por_servico
    return catalog


def _load_asset_mapping(domain: str) -> dict[str, str]:
    domain_safe = domain.replace(".", "_")
    assets_dir = BRIEFINGS_DIR / domain_safe / "assets"
    mapping: dict[str, str] = {}
    if not assets_dir.exists():
        return mapping
    snapshot = BRIEFINGS_DIR / f"{domain_safe}_snapshot.json"
    if snapshot.exists():
        try:
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            snapshot_domain = data.get("domain", "")
            if snapshot_domain and snapshot_domain.replace("www.", "") != domain.replace("www.", ""):
                logger.warning(
                    "Snapshot de assets ignorado: domínio do snapshot (%s) ≠ execução atual (%s)",
                    snapshot_domain,
                    domain,
                )
                return mapping
            mapping = data.get("asset_mapping", {})
        except json.JSONDecodeError:
            pass
    return mapping


def _copy_to_public(
    project_dir: Path,
    catalog: dict,
    asset_mapping: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Copia imagens para public/images. Retorna (IMAGENS, IMAGEM_POR_SERVICO)."""
    public_dir = project_dir / "public" / "images"
    public_dir.mkdir(parents=True, exist_ok=True)
    imagens: dict[str, str] = {}
    por_servico: dict[str, str] = {}

    def register(key: str, url: str, filename: str) -> str:
        if not url:
            return ""
        local_src = asset_mapping.get(url)
        dest = public_dir / filename
        if local_src and Path(local_src).exists():
            shutil.copy2(local_src, dest)
        elif url.startswith("http"):
            try:
                import httpx
                from config import USER_AGENT

                resp = httpx.get(
                    url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
                )
                if resp.status_code == 200:
                    dest.write_bytes(resp.content)
            except Exception as exc:
                logger.debug("Download %s: %s", url, exc)
                return url
        if dest.exists():
            return f"/images/{filename}"
        return url

    imagens["logo"] = register("logo", str(catalog.get("logo", "")), "logo.jpg")
    imagens["hero"] = register("hero", str(catalog.get("hero", "")), "hero.jpg")
    imagens["about"] = register("about", str(catalog.get("about", "")), "about.jpg")

    for slug, url in (catalog.get("porServico") or {}).items():
        safe = slug.replace("/", "-")
        por_servico[slug] = register(slug, url, f"servico-{safe}.jpg")

    return imagens, por_servico


def _extract_social_proof(site_data: SiteData, analysis: dict) -> list[dict]:
    text = " ".join(t for page in site_data.pages for t in page.get("texts", []))
    text += " ".join(page.get("html", "")[:5000] for page in site_data.pages)
    stats: list[dict] = []

    patterns = [
        (r"(\d+)[\s.,]?000|(\d+)\s*mil\+?", "mil+", "Clientes atendidos"),
        (r"(\d+)\s*anos", "anos", "Anos de experiência"),
        (r"(\d+)\s*%\s*(?:de\s+)?(?:satisfa|aprova)", "%", "Satisfação"),
        (r"(\d+)\+?\s*(?:projetos|instala)", "", "Projetos realizados"),
    ]
    for pattern, suffix, label in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            valor = int(next(g for g in match.groups() if g))
            stats.append({"valor": valor, "sufixo": suffix, "rotulo": label})

    n_services = len([
        p for p in site_data.pages if p.get("page_type") in ("servico", "servicos")
    ])
    if n_services and len(stats) < 4:
        stats.append({"valor": n_services, "sufixo": "", "rotulo": "Serviços"})

    niche = _infer_niche(analysis, site_data)
    if niche == "dental" and len(stats) < 4:
        stats.append({"valor": 100, "sufixo": "%", "rotulo": "Atendimento particular"})

    if len(stats) < 2:
        stats.append({"valor": len(site_data.pages), "sufixo": "", "rotulo": "Páginas de conteúdo"})

    return stats[:4]


def _whatsapp_digits(whatsapp: str) -> str:
    digits = re.sub(r"\D", "", whatsapp or "")
    if digits and not digits.startswith("55") and len(digits) in (10, 11):
        digits = "55" + digits
    return digits


def _resolve_endereco(contacts: dict) -> dict[str, str]:
    raw = contacts.get("endereco") or ""
    if not raw and contacts.get("addresses"):
        raw = contacts["addresses"][0]
    bairro = contacts.get("bairro", "")
    cidade = contacts.get("cidade", "")
    uf = contacts.get("uf", "")
    cep = ""
    if raw:
        cep_match = re.search(r"CEP\s*([\d-]+)", raw, re.I)
        if cep_match:
            cep = cep_match.group(1)
        uf_match = re.search(r"\b([A-Z]{2})\b", raw)
        if uf_match and not uf:
            uf = uf_match.group(1)
    return {
        "logradouro": raw or "Endereço não extraído",
        "bairro": bairro,
        "cidade": cidade or "Brasil",
        "uf": uf or "BR",
        "cep": cep,
    }


def _hero_copy(analysis: dict, site_data: SiteData, niche: str) -> dict[str, str]:
    business_name = analysis.get("business_name", site_data.domain)
    business_type = analysis.get("business_type", "negócio local")
    cidade = (site_data.contacts or {}).get("cidade", "")

    titulo = (
        analysis.get("value_proposition")
        or analysis.get("business_description", "").split(".")[0].strip()
        or business_name
    )
    subtitulo = business_type
    if cidade and cidade.lower() not in titulo.lower():
        subtitulo = f"{business_type} em {cidade.split(',')[0].strip()}"

    if niche == "dental":
        cta_primario = "Agendar avaliação"
        cta_secundario = "Ver tratamentos"
    elif niche == "energy":
        cta_primario = "Solicitar orçamento"
        cta_secundario = "Ver soluções"
    else:
        cta_primario = "Fale conosco"
        cta_secundario = "Ver serviços"

    aviso = ""
    if niche == "dental":
        aviso = "Não aceitamos convênios — atendimento exclusivamente particular."

    about_rotulo = f"Sobre {business_name.split()[0] if business_name else 'nós'}"

    return {
        "titulo": titulo,
        "subtitulo": subtitulo,
        "cta_primario": cta_primario,
        "cta_secundario": cta_secundario,
        "aviso": aviso,
        "about_rotulo": about_rotulo,
    }


def generate_constants_ts(site_data: SiteData, analysis: dict) -> str:
    _enrich_known_contacts(site_data)
    contacts = site_data.contacts or {}
    niche = _infer_niche(analysis, site_data)
    copy = _hero_copy(analysis, site_data, niche)

    business_name = analysis.get("business_name", site_data.domain)
    business_type = analysis.get("business_type", "negócio local")
    descricao = analysis.get("business_description") or analysis.get("value_proposition", "")
    descricao_curta = (descricao[:200] + "...") if len(descricao) > 200 else descricao
    if not descricao_curta:
        descricao_curta = copy["subtitulo"]

    endereco = _resolve_endereco(contacts)
    wa_digits = _whatsapp_digits(contacts.get("whatsapp", ""))
    telefone = contacts.get("telefone") or (
        contacts.get("telefones", [""])[0] if contacts.get("telefones") else ""
    )
    email = (contacts.get("emails") or [f"contato@{site_data.domain}"])[0]
    instagram = contacts.get("instagram", "")
    facebook = contacts.get("facebook", "")
    cro = contacts.get("cro", "") if niche == "dental" else ""

    desde = 0
    since_match = re.search(r"desde\s+(\d{4})", descricao, re.I)
    if since_match:
        desde = int(since_match.group(1))

    maps_query = quote(
        f"{endereco['logradouro']}, {endereco['bairro']}, {endereco['cidade']}-{endereco['uf']}"
    )
    prova = _extract_social_proof(site_data, analysis)
    prova_lines = ",\n  ".join(
        f'{{ valor: {s["valor"]}, sufixo: {_ts_string(s["sufixo"])}, rotulo: {_ts_string(s["rotulo"])} }}'
        for s in prova
    )

    wa_link_body = (
        f"  if (CONTATO.whatsappNumero) {{\n"
        f"    return `https://wa.me/${{CONTATO.whatsappNumero}}?text=${{encodeURIComponent(\n"
        f"      mensagem ?? CONTATO.whatsappMensagem\n"
        f"    )}}`;\n"
        f"  }}\n"
        f"  return REDES.instagram || {_ts_string(instagram)};"
    )

    servicos_label = "Tratamentos" if niche == "dental" else "Serviços"
    nome_curto = business_name.split()[0] if business_name else site_data.domain

    cro_line = f"  cro: {_ts_string(cro)},\n" if cro else ""

    desde_line = f"  desde: {desde},\n" if desde else ""

    return f"""/** Gerado automaticamente pelo scraping-agent — não editar manualmente. */

export const SITE = {{
  nome: {_ts_string(business_name)},
  nomeCurto: {_ts_string(nome_curto)},
  profissional: {_ts_string(business_name)},
  tipo: {_ts_string(business_type)},
  cidade: {_ts_string(endereco["cidade"])},
{desde_line}  url: {_ts_string("https://" + site_data.domain)},
  descricaoCurta: {_ts_string(descricao_curta)},
  descricaoLonga: {_ts_string(descricao or descricao_curta)},
}} as const;

export const HERO = {{
  titulo: {_ts_string(copy["titulo"])},
  subtitulo: {_ts_string(copy["subtitulo"])},
  ctaPrimario: {_ts_string(copy["cta_primario"])},
  ctaSecundario: {_ts_string(copy["cta_secundario"])},
  avisoDestaque: {_ts_string(copy["aviso"])},
  aboutRotulo: {_ts_string(copy["about_rotulo"])},
}} as const;

export const CONTATO = {{
  whatsappNumero: {_ts_string(wa_digits)},
  whatsappMensagem:
    {_ts_string(f"Olá! Vim pelo site da {business_name} e gostaria de mais informações.")},
  telefoneExibicao: {_ts_string(telefone or "Via WhatsApp")},
  email: {_ts_string(email)},
  endereco: {{
    logradouro: {_ts_string(endereco["logradouro"])},
    bairro: {_ts_string(endereco["bairro"])},
    cidade: {_ts_string(endereco["cidade"])},
    uf: {_ts_string(endereco["uf"])},
    cep: {_ts_string(endereco["cep"])},
  }},
  mapsEmbed: "https://www.google.com/maps?q={maps_query}&output=embed",
  mapsLink: "https://maps.google.com/?q={maps_query}",
{cro_line}}} as const;

export const whatsappLink = (mensagem?: string) => {{
{wa_link_body}
}};

export const REDES = {{
  instagram: {_ts_string(instagram)},
  facebook: {_ts_string(facebook)},
}} as const;

export const PROVA_SOCIAL = [
  {prova_lines},
] as const;

export const NAV = [
  {{ label: "Início", href: "/" }},
  {{ label: {_ts_string(servicos_label)}, href: "/tratamentos" }},
  {{ label: "Sobre", href: "/sobre" }},
  {{ label: "Blog", href: "/blog" }},
  {{ label: "Contato", href: "/contato" }},
] as const;
"""


def generate_images_ts(imagens: dict[str, str], por_servico: dict[str, str]) -> str:
    lines = [
        f'  logo: {_ts_string(imagens.get("logo", ""))},',
        f'  hero: {_ts_string(imagens.get("hero", ""))},',
        f'  about: {_ts_string(imagens.get("about", ""))},',
    ]
    map_lines = "\n".join(
        f"  {_ts_string(slug)}: {_ts_string(url)}," for slug, url in por_servico.items()
    )
    return f"""/** Gerado automaticamente pelo scraping-agent — não editar manualmente. */

export const IMAGENS = {{
{chr(10).join(lines)}
}} as const;

export const IMAGEM_POR_SERVICO: Record<string, string> = {{
{map_lines}
}};
"""


def generate_stats_ts() -> str:
    return '''"use client";

import { useEffect, useRef, useState } from "react";
import { PROVA_SOCIAL } from "@/lib/constants";

function Contador({ valor, sufixo }: { valor: number; sufixo: string }) {
  const [atual, setAtual] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const animou = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !animou.current) {
          animou.current = true;
          const inicio = performance.now();
          const tick = (agora: number) => {
            const p = Math.min((agora - inicio) / 1500, 1);
            setAtual(Math.floor(valor * p));
            if (p < 1) requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
        }
      },
      { threshold: 0.2 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [valor]);

  return (
    <div ref={ref} className="text-center">
      <p className="font-display text-4xl font-semibold text-osso md:text-5xl">
        {atual}
        {sufixo && <span className="text-2xl text-champanhe md:text-3xl">{sufixo}</span>}
      </p>
    </div>
  );
}

export function Stats() {
  return (
    <section className="border-y border-grafite/10 bg-grafite py-16 text-osso">
      <div className="container-clinica">
        <p className="rotulo mb-10 justify-center text-champanhe">Números que falam</p>
        <div className="grid grid-cols-2 gap-10 md:grid-cols-4">
          {PROVA_SOCIAL.map((item) => (
            <div key={item.rotulo}>
              <Contador valor={item.valor} sufixo={item.sufixo} />
              <p className="mt-2 text-center text-sm text-osso/70">{item.rotulo}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
'''


def generate_hero_ts() -> str:
    return '''import Image from "next/image";
import Link from "next/link";
import { MessageCircle, ArrowRight } from "lucide-react";
import { SITE, HERO, whatsappLink } from "@/lib/constants";
import { IMAGENS } from "@/lib/images";
import { Arco } from "@/components/ui/Arco";

export function Hero() {
  return (
    <section className="relative overflow-hidden bg-osso pb-20 pt-12 md:pb-28 md:pt-20">
      <div className="container-clinica grid items-center gap-12 lg:grid-cols-2">
        <div className="animate-fade-up">
          {SITE.desde ? (
            <p className="rotulo mb-6">Desde {SITE.desde} · {SITE.cidade}</p>
          ) : (
            <p className="rotulo mb-6">{SITE.tipo} · {SITE.cidade}</p>
          )}
          <h1 className="font-display text-4xl font-semibold leading-tight text-grafite md:text-5xl lg:text-6xl">
            <span className="arco-sublinhado">{HERO.titulo}</span>
          </h1>
          <p className="mt-4 text-lg text-texto-suave">{HERO.subtitulo}</p>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-texto-suave">{SITE.descricaoCurta}</p>
          {HERO.avisoDestaque && (
            <p className="mt-4 text-sm font-medium text-bronze">{HERO.avisoDestaque}</p>
          )}
          <div className="mt-8 flex flex-wrap gap-4">
            <a href={whatsappLink()} target="_blank" rel="noopener noreferrer" className="btn-cta">
              <MessageCircle className="h-4 w-4" /> {HERO.ctaPrimario}
            </a>
            <Link href="/tratamentos" className="btn-contorno">
              {HERO.ctaSecundario} <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
        {IMAGENS.hero && (
          <div className="relative hidden lg:block">
            <div className="overflow-hidden rounded-t-arco rounded-b-2xl shadow-cartao">
              <div className="relative aspect-[4/5]">
                <Image
                  src={IMAGENS.hero}
                  alt={`${SITE.nome} — ${SITE.cidade}`}
                  fill
                  className="object-cover object-top"
                  sizes="480px"
                  priority
                />
              </div>
            </div>
            <Arco className="absolute -bottom-2 left-0 text-bronze/40" cor="#9A7B4F" />
          </div>
        )}
      </div>
    </section>
  );
}
'''


def generate_about_ts() -> str:
    return '''import Image from "next/image";
import Link from "next/link";
import { SITE, HERO } from "@/lib/constants";
import { IMAGENS } from "@/lib/images";
import { ArcoMini } from "@/components/ui/Arco";

export function About() {
  return (
    <section className="bg-osso-fundo py-20 md:py-28">
      <div className="container-clinica grid items-center gap-12 lg:grid-cols-2">
        <div className="order-2 lg:order-1">
          <p className="rotulo mb-4"><ArcoMini /> {HERO.aboutRotulo}</p>
          <h2 className="font-display text-3xl font-semibold text-grafite md:text-4xl">{SITE.nome}</h2>
          <p className="mt-6 leading-relaxed text-texto-suave">{SITE.descricaoLonga}</p>
          <Link href="/sobre" className="btn-contorno mt-8">Conheça nossa história</Link>
        </div>
        {IMAGENS.about && (
          <div className="order-1 lg:order-2 relative aspect-[4/3] overflow-hidden rounded-2xl shadow-cartao">
            <Image src={IMAGENS.about} alt={SITE.nome} fill className="object-cover" sizes="560px" />
          </div>
        )}
      </div>
    </section>
  );
}
'''


def generate_arco_tsx() -> str:
    return '''type ArcoProps = {
  className?: string;
  cor?: string;
};

export function Arco({ className = "", cor = "currentColor" }: ArcoProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 120 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M0 38 Q60 0 120 38"
        stroke={cor}
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function ArcoMini({ className = "", cor = "currentColor" }: ArcoProps) {
  return (
    <svg
      className={`inline-block h-4 w-4 align-middle ${className}`}
      viewBox="0 0 24 12"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M0 11 Q12 0 24 11"
        stroke={cor}
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}
'''


def validate_injection_sanity(
    domain: str,
    analysis: dict,
    *contents: str,
) -> None:
    """
    Detecta contaminação cruzada entre nichos antes de gravar arquivos.
    Levanta ValueError se o conteúdo não corresponder ao domínio/analysis atual.
    """
    combined = " ".join(contents).lower()
    domain_l = domain.replace("www.", "").lower()

    business_hay = " ".join(
        str(analysis.get(k, "")) for k in ("business_name", "business_type", "business_description")
    ).lower()

    dental_in_content = any(m in combined for m in NICHE_MARKERS["dental"])
    energy_in_content = any(m in combined for m in NICHE_MARKERS["energy"])

    class _DomainOnly:
        domain: str

        def __init__(self, d: str) -> None:
            self.domain = d

    expected_niche = _infer_niche(analysis, _DomainOnly(domain))  # type: ignore[arg-type]

    conflicts: list[str] = []

    if expected_niche == "energy" and dental_in_content:
        hits = [m for m in NICHE_MARKERS["dental"] if m in combined]
        if not any(m in business_hay for m in hits):
            conflicts.append(
                f"domínio/nicho energia ({domain}) mas conteúdo contém marcadores odontológicos: {hits[:3]}"
            )

    if expected_niche == "dental" and energy_in_content:
        hits = [m for m in NICHE_MARKERS["energy"] if m in combined]
        if not any(m in business_hay for m in hits):
            conflicts.append(
                f"domínio/nicho odontologia ({domain}) mas conteúdo contém marcadores de energia: {hits[:3]}"
            )

    if "genforce" in domain_l and dental_in_content:
        hits = [m for m in NICHE_MARKERS["dental"] if m in combined]
        conflicts.append(
            f"genforce.com.br não deve conter conteúdo odontológico: {hits[:3]}"
        )

    if any(k in domain_l for k in ("viviane", "draviviane", "odont")) and energy_in_content:
        if "genforce" in combined or "gerador" in combined:
            conflicts.append("domínio odontológico contém conteúdo de energia/geradores")

    if conflicts:
        msg = (
            "Validação de sanidade FALHOU — possível contaminação entre clientes:\n  - "
            + "\n  - ".join(conflicts)
        )
        logger.error(msg)
        raise ValueError(msg)


def save_site_snapshot(site_data: SiteData, asset_mapping: dict[str, str], catalog: dict) -> Path:
    domain_safe = site_data.domain.replace(".", "_")
    path = BRIEFINGS_DIR / f"{domain_safe}_snapshot.json"
    payload = {
        "domain": site_data.domain,
        "contacts": site_data.contacts,
        "asset_mapping": asset_mapping,
        "image_catalog": catalog,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def inject_scraped_content(
    project_path: str,
    site_data: SiteData,
    analysis: dict,
) -> list[str]:
    """
    Sobrescreve lib/constants.ts, lib/images.ts e componentes críticos
    com dados reais extraídos pelo scraping da execução atual.
    """
    project_dir = Path(project_path)
    if not project_dir.exists():
        return []

    analysis = analysis or {}
    business_name = analysis.get("business_name", "(não informado)")

    logger.info(
        "site_injector: preparando injeção — domain=%s | business_name=%s | project=%s",
        site_data.domain,
        business_name,
        project_path,
    )

    _enrich_known_contacts(site_data)
    catalog = build_image_catalog(site_data, analysis)
    asset_mapping = _load_asset_mapping(site_data.domain)
    imagens, por_servico = _copy_to_public(project_dir, catalog, asset_mapping)

    constants_content = generate_constants_ts(site_data, analysis)
    images_content = generate_images_ts(imagens, por_servico)
    stats_content = generate_stats_ts()
    hero_content = generate_hero_ts()
    about_content = generate_about_ts()
    arco_content = generate_arco_tsx()

    validate_injection_sanity(
        site_data.domain,
        analysis,
        constants_content,
        images_content,
        hero_content,
        about_content,
    )

    written: list[str] = []

    lib_dir = project_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)

    constants_file = lib_dir / "constants.ts"
    constants_file.write_text(constants_content, encoding="utf-8")
    written.append("lib/constants.ts")

    images_file = lib_dir / "images.ts"
    images_file.write_text(images_content, encoding="utf-8")
    written.append("lib/images.ts")

    home_dir = project_dir / "components" / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (
        ("Stats.tsx", stats_content),
        ("Hero.tsx", hero_content),
        ("About.tsx", about_content),
    ):
        target = home_dir / name
        target.write_text(content, encoding="utf-8")
        written.append(f"components/home/{name}")

    ui_dir = project_dir / "components" / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    arco_file = ui_dir / "Arco.tsx"
    arco_file.write_text(arco_content, encoding="utf-8")
    written.append("components/ui/Arco.tsx")

    domain_host = urlparse(f"https://{site_data.domain}").hostname or site_data.domain
    for cfg_name in ("next.config.mjs", "next.config.ts"):
        next_config = project_dir / cfg_name
        if not next_config.exists():
            continue
        text = next_config.read_text(encoding="utf-8")
        if domain_host in text:
            break
        if "remotePatterns" in text:
            text = text.replace(
                "remotePatterns: [",
                f'remotePatterns: [\n      {{ protocol: "https", hostname: "{domain_host}" }},',
                1,
            )
            next_config.write_text(text, encoding="utf-8")
            written.append(cfg_name)
        break

    logger.info(
        "Dados do scraping injetados em %s (domain=%s, business_name=%s): %s",
        project_path,
        site_data.domain,
        business_name,
        ", ".join(written),
    )
    return written
