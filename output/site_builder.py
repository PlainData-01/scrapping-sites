"""Reconstrução de site Next.js + Tailwind a partir do briefing extraído."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import OUTPUT_DIR, SiteData
from output.site_injector import inject_scraped_content

logger = logging.getLogger(__name__)

SITES_OUTPUT_DIR = Path(OUTPUT_DIR) / "sites"


async def _run_command(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = 300,
) -> tuple[int, str, str]:
    """
    Executa comando externo via subprocess.run em thread separada.

    Evita o bug do asyncio no Windows (ValueError: I/O operation on closed pipe)
    que ocorre com create_subprocess_exec + ProactorEventLoop.
    """
    resolved = list(cmd)
    if resolved and sys.platform == "win32":
        path = shutil.which(resolved[0])
        if path:
            resolved[0] = path

    def _sync() -> tuple[int, str, str]:
        try:
            result = subprocess.run(
                resolved,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                timeout=timeout,
                text=True,
                errors="replace",
            )
            return result.returncode, result.stdout or "", result.stderr or ""
        except subprocess.TimeoutExpired:
            return -1, "", f"Timeout após {int(timeout)}s"
        except FileNotFoundError:
            raise

    return await asyncio.to_thread(_sync)


async def _setup_impeccable(project_dir: Path) -> bool:
    """Instala skill Impeccable no projeto Next.js do cliente."""
    project_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Instalando Impeccable em %s...", project_dir)
    try:
        code, _, err = await _run_command(
            [
                "npx", "--yes", "impeccable@latest", "install",
                "--providers=claude", "--scope=project", "--no-hooks",
            ],
            cwd=project_dir,
            timeout=180,
        )
        if code == 0:
            logger.info("Impeccable instalado com sucesso")
            return True
        logger.warning("Impeccable install code=%s: %s", code, err[:400])
    except FileNotFoundError:
        logger.warning("npx não encontrado — Impeccable não instalado")
    except Exception as exc:
        logger.warning("Falha ao instalar Impeccable: %s", exc)
    return False


DEFAULT_TREATMENTS = [
    "invisalign",
    "ortodontia",
    "alinhadores",
    "clareamento",
    "odontopediatria",
    "periodontia",
    "bruxismo",
    "atm",
    "cirurgia-ortognatica",
    "apneia-ronco",
    "polissonografia",
    "clinica-geral",
]


def _extract_section_9(briefing: str) -> str:
    """Extrai o bloco de prompt da seção 9 do briefing."""
    match = re.search(
        r"### PROMPT PARA LOVABLE.*?```(.*?)```",
        briefing,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    match = re.search(r"## 9\..*?---\n(.*?)---", briefing, re.DOTALL)
    if match:
        return match.group(1).strip()

    return briefing[-3000:]


def _detect_treatments(site_data: SiteData) -> list[str]:
    """Identifica páginas de tratamento existentes no site original."""
    treatments: list[str] = []
    seen: set[str] = set()

    for page in site_data.pages:
        if page.get("page_type") not in ("servico", "servicos"):
            continue
        url = page.get("url", "")
        slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
        slug = re.sub(r"[^a-z0-9-]", "-", slug).strip("-")
        if slug and slug not in seen and slug not in ("servicos", "tratamentos"):
            seen.add(slug)
            treatments.append(slug)

    if len(treatments) < 3:
        for default in DEFAULT_TREATMENTS:
            if default not in seen:
                treatments.append(default)
                seen.add(default)

    return treatments[:15]


def _whatsapp_to_link(whatsapp: str) -> str:
    """Converte WhatsApp para URL wa.me limpa."""
    if not whatsapp:
        return "https://wa.me/PREENCHER"
    digits = re.sub(r"\D", "", whatsapp)
    if not digits:
        return "https://wa.me/PREENCHER"
    if not digits.startswith("55") and len(digits) in (10, 11):
        digits = "55" + digits
    return f"https://wa.me/{digits}"


def _format_treatments_tree(treatments: list[str]) -> str:
    """Formata árvore de pastas dos tratamentos."""
    return "\n".join(
        f"│   │   ├── {t}/page.tsx" for t in treatments
    )


def _build_design_brief_section(analysis: dict) -> str:
    """Monta a seção de briefing de design para o prompt final."""
    dd = analysis.get("design_direction", {})
    niche = analysis.get("niche_category", "outro")

    return f"""
## PROCESSO DE DESIGN — LEIA ANTES DE CODAR

Antes de escrever qualquer código, você deve agir como o lead de design
de um pequeno estúdio que dá a cada cliente uma identidade visual que
não poderia ser confundida com a de outro cliente.

**Briefing deste cliente específico:**
- Nicho: {niche}
- Tom visual correto para este negócio: {dd.get('tone', 'a definir com base no conteúdo')}
- Evite estes clichês do setor: {dd.get('avoid', '')}
- Mood de cor (a traduzir em hex): {dd.get('color_mood', '')}
- Mood de tipografia (a traduzir em fontes reais): {dd.get('typography_mood', '')}
- Elemento de assinatura a explorar: {dd.get('signature_element', '')}
- Como a concorrência se apresenta tipicamente (NÃO repita isso): {analysis.get('competitor_baseline', '')}

**Processo obrigatório, em duas passadas:**

PASSADA 1 — Plano de design (escreva isso ANTES de criar qualquer arquivo):
- Paleta: 4-6 cores nomeadas com hex, derivadas do mood acima
- Tipografia: 2 fontes (uma de display com personalidade, uma de corpo
  legível), escolhidas para refletir o tom deste negócio específico
- Layout: descreva em 1-2 frases o conceito de layout do Hero e como
  ele comunica a coisa mais característica deste negócio
- Assinatura: o elemento único que vai tornar este site memorável

PASSADA 2 — Crítica do próprio plano:
- Revise o plano da Passada 1. Se qualquer parte dele poderia servir
  para QUALQUER outro negócio do mesmo setor genérico (ex: qualquer
  clínica odontológica, qualquer empresa de energia), troque essa parte
  por algo mais específico a ESTE negócio.
- Evite especificamente: fundo creme com serif e terracota; fundo quase
  preto com um único acento neon; ou layout estilo jornal com colunas
  densas — a menos que o briefing realmente peça isso.
- Escreva o que você mudou e por quê.

Só depois de completar as duas passadas, comece a criar os arquivos,
seguindo o plano revisado.
"""


def _build_reconstruction_prompt(
    site_data: SiteData,
    analysis: dict,
    section_9: str,
) -> str:
    """Monta o prompt completo de reconstrução para o Cursor Agent."""
    domain = site_data.domain
    domain_slug = domain.replace(".", "_")
    business_name = analysis.get("business_name", domain)
    business_type = analysis.get("business_type", "negócio local")
    colors = site_data.colors[:5] if site_data.colors else []
    contacts = site_data.contacts or {}

    image_urls: list[dict] = []
    seen_imgs: set[str] = set()
    for page in site_data.pages:
        for img in page.get("images", [])[:3]:
            url = img.get("src") or img.get("url", "")
            alt = img.get("alt", "")
            if url and not url.startswith("data:") and url not in seen_imgs:
                seen_imgs.add(url)
                image_urls.append({"url": url, "alt": alt})

    images_block = "\n".join(
        f"- {img['url']} ({img['alt'] or 'sem alt'})"
        for img in image_urls[:20]
    ) or "- (nenhuma imagem extraída — usar placeholders)"

    whatsapp = contacts.get("whatsapp") or "PREENCHER_NUMERO"
    whatsapp_link = _whatsapp_to_link(whatsapp)
    endereco = contacts.get("endereco") or (
        contacts.get("addresses", [""])[0] if contacts.get("addresses") else "PREENCHER_ENDEREÇO"
    )
    instagram = contacts.get("instagram", "")
    facebook = contacts.get("facebook", "")
    cro = contacts.get("cro", "")
    cidade = contacts.get("cidade", "Brasília")

    treatments = _detect_treatments(site_data)
    treatments_tree = _format_treatments_tree(treatments)
    treatments_list = ", ".join(t.replace("-", " ").title() for t in treatments)

    seo_table_rows: list[str] = [
        f"| Home | {business_name} — {business_type} em {cidade} | "
        f"{analysis.get('value_proposition', business_type)} |",
        f"| Sobre | Sobre {business_name} | "
        f"{analysis.get('business_description', '')[:120]} |",
    ]
    for slug in treatments[:5]:
        title_friendly = slug.replace("-", " ").title()
        seo_table_rows.append(
            f"| {title_friendly} | {title_friendly} — {business_name} | "
            f"{title_friendly} em {cidade}. {business_name}. |"
        )
    seo_table = "\n".join(seo_table_rows)

    design_brief = _build_design_brief_section(analysis)

    prompt = f"""Você é um desenvolvedor senior especializado em Next.js 14, Tailwind CSS e design de alta conversão.

Sua tarefa é criar um projeto Next.js completo para {business_name}, uma {business_type} em {cidade}.
O projeto deve ser production-ready, com foco em conversão, SEO e identidade visual específica deste negócio.

---

## CONTEXTO DO CLIENTE

{section_9}

---

{design_brief}

---

## ESPECIFICAÇÕES TÉCNICAS OBRIGATÓRIAS

### Stack
- Next.js 14 com App Router
- Tailwind CSS
- TypeScript
- Framer Motion para animações suaves
- next-seo para SEO
- shadcn/ui para componentes base

### Estrutura de pastas

IMPORTANTE: crie os arquivos DIRETAMENTE na raiz do diretório de trabalho
atual (onde está BUILD_PROMPT.md). NÃO crie subpasta com o nome do domínio.

```
./
├── app/
│   ├── layout.tsx              # Layout global com header, footer, WhatsApp flutuante
│   ├── page.tsx                # Home
│   ├── sobre/page.tsx          # Sobre a clínica / profissional
│   ├── contato/page.tsx        # Contato com mapa e formulário
│   ├── tratamentos/
│   │   ├── page.tsx            # Índice de tratamentos
{treatments_tree}
│   └── blog/
│       └── page.tsx
├── components/
│   ├── layout/
│   │   ├── Header.tsx          # Nav com menu dropdown de tratamentos
│   │   ├── Footer.tsx          # Endereço, mapa, redes sociais, links
│   │   └── WhatsAppButton.tsx  # Botão flutuante fixo
│   ├── home/
│   │   ├── Hero.tsx            # Hero com headline, prova social e CTA
│   │   ├── Stats.tsx           # Contador: 21mil pacientes, 30 anos, etc.
│   │   ├── Treatments.tsx      # Grid de cards de tratamentos
│   │   ├── About.tsx           # Seção sobre a profissional com foto
│   │   ├── Testimonials.tsx    # Depoimentos de pacientes
│   │   └── CTA.tsx             # Seção de chamada para agendamento
│   ├── tratamento/
│   │   ├── TreatmentHero.tsx   # Hero de cada página de tratamento
│   │   ├── TreatmentContent.tsx
│   │   └── TreatmentCTA.tsx
│   └── ui/
│       ├── FAQ.tsx             # FAQ expansível por tratamento
│       └── ContactForm.tsx     # Formulário integrado com WhatsApp
├── lib/
│   ├── constants.ts            # Dados do cliente (nome, contatos, etc.)
│   └── treatments.ts           # Dados de cada tratamento
├── public/
│   └── images/                 # Imagens do cliente (usar URLs externas por ora)
├── tailwind.config.ts
├── next.config.ts
└── package.json
```

Use as cores e tipografia definidas no PROCESSO DE DESIGN acima.
Derive o visual do briefing deste cliente — não use paletas ou fontes
genéricas de outros projetos.

Cores detectadas no site atual (referência, não obrigatório copiar): {', '.join(colors) if colors else 'nenhuma detectada'}

---

## DADOS REAIS DO CLIENTE

### Contatos
- WhatsApp: {whatsapp}
- Link WhatsApp pronto: {whatsapp_link}
- Endereço: {endereco}
- Instagram: {instagram or 'NÃO INFORMADO'}
- Facebook: {facebook or 'NÃO INFORMADO'}
- CRO/Registro: {cro or 'NÃO INFORMADO'}

### Serviços / páginas detectadas
{treatments_list}

### Imagens disponíveis (usar estas URLs reais)
{images_block}

---

## COMPONENTES CRÍTICOS DE CONVERSÃO

### 1. WhatsApp Flutuante (presente em TODAS as páginas)

```tsx
// components/layout/WhatsAppButton.tsx
// Botão fixo no canto inferior direito
// Animação de pulse suave para chamar atenção
// Link: {whatsapp_link}
// Texto ao hover: use CTA adequado ao negócio
```

### 2. Hero da Home

```tsx
// Headline e subheadline baseados no conteúdo real extraído (seção 9)
// CTA primário: WhatsApp → {whatsapp_link}
// CTA secundário: página principal de serviços → /tratamentos ou equivalente
// Prova social: use credenciais reais do briefing, não números inventados
```

### 3. Stats Counter (se houver dados numéricos no briefing)

```tsx
// Animar contadores com framer-motion ao entrar na viewport
// Usar APENAS números e credenciais extraídos do site real
```

### 4. Cards de Serviços/Tratamentos

```tsx
// Grid responsivo com hover effect
// Cada card: ícone ou imagem + nome + descrição curta + "Saiba mais"
// Itens: {treatments_list}
```

### 5. FAQ por página de serviço

```tsx
// Componente FAQ reutilizável com accordion
// Gerar 4-5 perguntas relevantes por serviço com base no conteúdo
```

### 6. Schema.org JSON-LD

```tsx
// Em app/layout.tsx, adicionar schema adequado ao tipo de negócio:
// LocalBusiness + tipo específico (MedicalOrganization, Store, etc.)
// Incluir: name, address, telephone, url quando disponíveis
```

### 7. Footer completo

```tsx
// Logo + descrição curta
// Menu de serviços
// Contato: endereço completo + mapa embed do Google Maps quando possível
// Redes sociais disponíveis
// {cro or 'Registro profissional quando aplicável'}
// Copyright
```

---

## SEO POR PÁGINA

Gerar metadata completo para cada página seguindo este padrão:

| Página | Title | Description |
|--------|-------|-------------|
{seo_table}

(Repetir o padrão para todas as páginas de tratamento)

---

## ORDEM DE CRIAÇÃO

Crie os arquivos nesta ordem para eu poder testar incrementalmente:

1. `package.json` + `tailwind.config.ts` + `next.config.ts`
2. `lib/constants.ts` com TODOS os dados do cliente acima
3. `lib/treatments.ts` com dados de cada tratamento
4. `components/layout/Header.tsx`
5. `components/layout/Footer.tsx`
6. `components/layout/WhatsAppButton.tsx`
7. `components/home/Hero.tsx`
8. `components/home/Stats.tsx`
9. `components/home/Treatments.tsx`
10. `components/home/About.tsx`
11. `components/home/Testimonials.tsx`
12. `app/layout.tsx`
13. `app/page.tsx` (Home completa)
14. `app/sobre/page.tsx`
15. `app/tratamentos/page.tsx`
16. Uma página de tratamento modelo (invisalign)
17. Replicar estrutura para os demais tratamentos
18. `app/contato/page.tsx`
19. `app/blog/page.tsx`
20. Ajustes finais de SEO e Schema.org

Crie todos os arquivos necessários para um projeto funcional completo.

---

## DESIGN COM IMPECCABLE

Este diretório inclui a skill **Impeccable** (design language para IA).
Siga estes princípios ao construir o site — evite o visual genérico de IA:

- **Tipografia:** não use Inter, Arial ou system-ui como fonte principal. Escolha
  uma fonte com personalidade adequada ao nicho (ex.: serif elegante para clínica
  premium, geometric sans para tech).
- **Cores:** não use gradientes roxo→azul genéricos. Tintas nas cores neutras
  (nunca preto/cinza puro). Contraste legível em textos sobre fundos coloridos.
- **Layout:** evite cards dentro de cards. Hierarquia clara, respiro generoso,
  ritmo visual consistente.
- **Motion:** animações sutis com easing natural (evite bounce/elastic).
- **Conversão:** CTAs claros, prova social real, WhatsApp sempre acessível.

Se a skill Impeccable estiver instalada em `.claude/skills/impeccable/`, consulte
os comandos `/impeccable polish`, `/impeccable audit` e `/impeccable layout` como
referência de qualidade antes de finalizar.

OBRIGATÓRIO para o site funcionar: app/layout.tsx, app/page.tsx,
app/tratamentos/page.tsx, app/tratamentos/[slug]/page.tsx (para cada slug),
postcss.config.mjs e next.config. Sem app/page.tsx o servidor retorna 404.

NOTA: lib/constants.ts, lib/images.ts e components/home/{{Stats,Hero,About}}.tsx
serão SOBRESCRITOS automaticamente pelo pipeline com dados reais do scraping
(contatos, fotos, números). Use imports de @/lib/constants e @/lib/images.
"""

    return prompt


CRITICAL_ROUTE_FILES = (
    "app/layout.tsx",
    "app/page.tsx",
    "app/tratamentos/page.tsx",
    "postcss.config.mjs",
)


def _missing_critical_files(project_dir: Path) -> list[str]:
    """Lista arquivos de rota obrigatórios ausentes no projeto gerado."""
    return [
        rel for rel in CRITICAL_ROUTE_FILES
        if not (project_dir / rel).exists()
    ]


def _scaffold_missing_routes(project_dir: Path, analysis: dict) -> list[str]:
    """
    Preenche rotas mínimas quando a geração via Claude Code ficou incompleta.
    Retorna a lista de arquivos criados.
    """
    created: list[str] = []
    business_name = analysis.get("business_name", "Site")
    business_type = analysis.get("business_type", "negócio local")

    postcss = project_dir / "postcss.config.mjs"
    if not postcss.exists():
        postcss.write_text(
            '/** @type {import("postcss-load-config").Config} */\n'
            "const config = { plugins: { tailwindcss: {}, autoprefixer: {} } };\n"
            "export default config;\n",
            encoding="utf-8",
        )
        created.append("postcss.config.mjs")

    layout = project_dir / "app" / "layout.tsx"
    if not layout.exists():
        layout.parent.mkdir(parents=True, exist_ok=True)
        layout.write_text(
            f'''import type {{ Metadata }} from "next";
import "./globals.css";

export const metadata: Metadata = {{
  title: "{business_name}",
  description: "{business_type}",
}};

export default function RootLayout({{ children }}: {{ children: React.ReactNode }}) {{
  return (
    <html lang="pt-BR">
      <body>{{children}}</body>
    </html>
  );
}}
''',
            encoding="utf-8",
        )
        created.append("app/layout.tsx")

    page = project_dir / "app" / "page.tsx"
    if not page.exists():
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            f'''export default function HomePage() {{
  return (
    <main className="mx-auto max-w-4xl px-6 py-20">
      <h1 className="text-4xl font-bold">{business_name}</h1>
      <p className="mt-4 text-lg text-gray-600">{business_type}</p>
      <p className="mt-8">
        <a href="/tratamentos" className="text-blue-600 underline">
          Ver tratamentos
        </a>
      </p>
    </main>
  );
}}
''',
            encoding="utf-8",
        )
        created.append("app/page.tsx")

    trat_index = project_dir / "app" / "tratamentos" / "page.tsx"
    if not trat_index.exists():
        trat_index.parent.mkdir(parents=True, exist_ok=True)
        trat_index.write_text(
            f'''import Link from "next/link";

export default function TratamentosPage() {{
  return (
    <main className="mx-auto max-w-4xl px-6 py-20">
      <h1 className="text-3xl font-bold">Tratamentos — {business_name}</h1>
      <p className="mt-4">
        <Link href="/" className="text-blue-600 underline">Voltar ao início</Link>
      </p>
    </main>
  );
}}
''',
            encoding="utf-8",
        )
        created.append("app/tratamentos/page.tsx")

    slug_page = project_dir / "app" / "tratamentos" / "[slug]" / "page.tsx"
    if not slug_page.exists():
        slug_page.parent.mkdir(parents=True, exist_ok=True)
        slug_page.write_text(
            '''export default function TratamentoSlugPage({
  params,
}: {
  params: { slug: string };
}) {
  return (
    <main className="mx-auto max-w-4xl px-6 py-20">
      <h1 className="text-3xl font-bold capitalize">
        {params.slug.replace(/-/g, " ")}
      </h1>
    </main>
  );
}
''',
            encoding="utf-8",
        )
        created.append("app/tratamentos/[slug]/page.tsx")

    return created


async def _repair_incomplete_project(
    project_path: str,
    site_data: SiteData,
    analysis: dict,
) -> list[str]:
    """
    Detecta projeto incompleto, tenta continuação via Claude Code e, se
    necessário, aplica scaffold mínimo para evitar 404 na raiz.
    """
    project_dir = Path(project_path)
    missing = _missing_critical_files(project_dir)
    if not missing:
        return []

    logger.warning(
        "Projeto incompleto em %s — arquivos ausentes: %s",
        project_path,
        ", ".join(missing),
    )

    if _check_claude_code_available():
        continuation = (
            "O projeto Next.js neste diretório está INCOMPLETO. "
            f"Faltam estes arquivos obrigatórios: {', '.join(missing)}. "
            "Leia BUILD_PROMPT.md e crie TODOS os arquivos que faltam, "
            "especialmente app/layout.tsx, app/page.tsx e as rotas em "
            "app/tratamentos/. Não crie subpastas extras — use a raiz atual."
        )
        await _execute_claude_code(
            continuation, project_path, site_data, max_turns=40
        )
        missing = _missing_critical_files(project_dir)
        if not missing:
            logger.info("Continuação via Claude Code completou os arquivos ausentes.")
            return []

    created = _scaffold_missing_routes(project_dir, analysis or {})
    if created:
        logger.warning(
            "Scaffold mínimo aplicado (Claude Code incompleto): %s",
            ", ".join(created),
        )
    return created


def _check_claude_code_available() -> bool:
    """Verifica se o Claude Code CLI está instalado e disponível no PATH."""
    for name in ("claude", "claude.cmd", "claude.exe", "claude.ps1"):
        if shutil.which(name):
            return True
    return False


def _resolve_claude_command() -> str:
    """Resolve o caminho completo do Claude Code CLI neste sistema."""
    for name in ("claude", "claude.cmd", "claude.exe", "claude.ps1"):
        path = shutil.which(name)
        if path:
            return path
    return "claude"


async def _execute_claude_code(
    prompt: str,
    project_path: str,
    site_data: SiteData,
    max_turns: int = 60,
) -> str:
    """
    Executa o Claude Code CLI em modo não-interativo para gerar o
    projeto Next.js completo, sem intervenção manual.
    """
    project_dir = Path(project_path)
    project_dir.mkdir(parents=True, exist_ok=True)

    if not _check_claude_code_available():
        logger.warning(
            "Claude Code CLI não encontrado no PATH. "
            "Instale com: npm install -g @anthropic-ai/claude-code. "
            "Prompt salvo para uso manual."
        )
        return ""

    claude_cmd = _resolve_claude_command()
    logger.info("Comando Claude Code resolvido: %s", claude_cmd)

    prompt_file = project_dir / "BUILD_PROMPT.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    logger.info("Prompt salvo em %s (%d chars) — evita limite de linha de comando no Windows", prompt_file, len(prompt))

    short_prompt = (
        "Leia e execute integralmente todas as instruções em BUILD_PROMPT.md "
        "neste diretório. Crie todos os arquivos do projeto Next.js conforme especificado."
    )

    logger.info(
        "Executando Claude Code CLI para %s (isso pode levar alguns minutos)...",
        site_data.domain,
    )

    cmd = [
        claude_cmd,
        "--print",
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep",
        "--permission-mode", "acceptEdits",
        short_prompt,
    ]

    logger.info(
        "Disparando subprocess Claude Code CLI. Comando: %s",
        " ".join(cmd[:5]) + " ... [prompt via BUILD_PROMPT.md, %d chars]" % len(prompt),
    )

    try:
        returncode, stdout, stderr = await _run_command(
            cmd, cwd=project_dir, timeout=900,
        )

        if returncode != 0:
            logger.error(
                "Claude Code CLI retornou erro (code %s): %s",
                returncode,
                stderr[:2000],
            )
            return str(project_dir)

        try:
            result = json.loads(stdout)
            logger.info(
                "Claude Code concluído. Turnos: %s | Duração: %ss | Custo: $%s",
                result.get("num_turns", "?"),
                result.get("duration_ms", 0) // 1000,
                result.get("total_cost_usd", "?"),
            )
        except (json.JSONDecodeError, KeyError):
            logger.info("Claude Code concluído (output não-JSON recebido).")

        return str(project_dir)

    except FileNotFoundError as exc:
        logger.error(
            "Comando '%s' não encontrado. Verifique se o Claude Code CLI "
            "está instalado e no PATH. Erro: %s", cmd[0], exc,
        )
        return str(project_dir)

    except Exception as exc:
        logger.error("Erro ao executar Claude Code CLI: %s", exc, exc_info=True)
        return str(project_dir)


async def _post_process_project(project_path: str) -> dict:
    """
    Após a geração do projeto, tenta npm install e verifica se o
    projeto builda sem erros. Retorna status para o relatório final.
    """
    project_dir = Path(project_path)
    status = {"npm_install": False, "build_ok": False, "errors": ""}

    if not (project_dir / "package.json").exists():
        status["errors"] = "package.json não encontrado — projeto incompleto"
        return status

    try:
        install_code, _, install_err = await _run_command(
            ["npm", "install"], cwd=project_dir, timeout=300,
        )
        status["npm_install"] = install_code == 0

        if not status["npm_install"]:
            status["errors"] = install_err[:1000]
            return status

        build_code, _, build_err = await _run_command(
            ["npm", "run", "build"], cwd=project_dir, timeout=300,
        )
        status["build_ok"] = build_code == 0
        if not status["build_ok"]:
            status["errors"] = build_err[:1000]

    except FileNotFoundError:
        status["errors"] = "npm não encontrado no PATH"
    except Exception as exc:
        status["errors"] = str(exc)

    return status


async def build_site(
    site_data: SiteData,
    analysis: dict,
    briefing_path: str,
) -> tuple[str, dict]:
    """
    Lê o briefing, monta o prompt de reconstrução (já com a direção de
    design da Parte 1) e executa via Claude Code CLI para gerar o
    projeto Next.js completo de forma 100% automática.

    Retorna (caminho do projeto, status de pós-processamento).
    """
    post_status: dict = {"npm_install": False, "build_ok": False, "errors": ""}

    logger.info("build_site() iniciado. briefing_path=%r", briefing_path)

    if not briefing_path or not Path(briefing_path).exists():
        logger.warning("Briefing não encontrado: %s", briefing_path)
        return "", post_status

    briefing = Path(briefing_path).read_text(encoding="utf-8")
    section_9 = _extract_section_9(briefing)
    prompt = _build_reconstruction_prompt(site_data, analysis or {}, section_9)

    domain_slug = site_data.domain.replace(".", "_")
    prompt_path = SITES_OUTPUT_DIR / f"{domain_slug}_cursor_prompt.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    logger.info("Prompt de reconstrução salvo em: %s", prompt_path)

    project_path = str(SITES_OUTPUT_DIR / domain_slug)

    await _setup_impeccable(Path(project_path))

    if _check_claude_code_available():
        logger.info(
            "Claude Code CLI detectado (%s). Iniciando geração do projeto...",
            _resolve_claude_command(),
        )
        project_path = await _execute_claude_code(prompt, project_path, site_data)
        if project_path:
            await _repair_incomplete_project(
                project_path, site_data, analysis or {}
            )
            inject_scraped_content(project_path, site_data, analysis or {})
            post_status = await _post_process_project(project_path)
            if post_status["build_ok"]:
                logger.info("✅ Projeto validado: npm install e build concluídos com sucesso")
            elif post_status["npm_install"]:
                logger.warning(
                    "⚠️ npm install OK, mas o build falhou: %s",
                    post_status["errors"][:300],
                )
            else:
                logger.warning(
                    "⚠️ npm install falhou: %s",
                    post_status["errors"][:300],
                )
    else:
        logger.warning(
            "Claude Code CLI não disponível. "
            "Instale com 'npm install -g @anthropic-ai/claude-code' "
            "para automação completa, ou cole %s manualmente no Cursor Agent.",
            prompt_path,
        )
        project_dir = Path(project_path)
        project_dir.mkdir(parents=True, exist_ok=True)
        inject_scraped_content(project_path, site_data, analysis or {})

    return project_path, post_status
