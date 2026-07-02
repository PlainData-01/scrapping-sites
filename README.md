# Prospect Hub (scrapping-sites) — v3.2

Ferramenta interna para prospecção comercial, análise de sites, mensagens WhatsApp, mini diagnósticos e protótipos rápidos.

**v3.2** foca em validação operacional, UX do workspace e checklist E2E com Supabase.

## Documentação

| Documento | Conteúdo |
|-----------|----------|
| [docs/SETUP.md](docs/SETUP.md) | Instalação, `.env`, Supabase, comandos |
| [docs/E2E_CHECKLIST.md](docs/E2E_CHECKLIST.md) | **Teste manual ponta a ponta** |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Estrutura de pastas, fluxos, endpoints |
| [docs/CHANGELOG_v32.md](docs/CHANGELOG_v32.md) | Release v3.2 |
| [docs/CHANGELOG_v31.md](docs/CHANGELOG_v31.md) | Release v3.1 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Próximos passos |

## Início rápido

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
python api.py
```

Abra http://127.0.0.1:8000

## Estrutura resumida

```
api.py, agent.py          # Entry points
config/icps/              # Perfis por nicho
prospector/               # Pipeline comercial
parser/, crawler/         # Análise e scraping
output/                   # Geradores (.py versionados; artefatos gitignored)
storage/                  # Supabase / SQLite
templates/                # UI + protótipos JSON
supabase/migrations/      # SQL incremental
tests/                    # Testes pytest
docs/                     # Documentação
```

## Fluxo comercial

```
ICP → Prospectar → Workspace → Mensagem → Status → Diagnóstico → Protótipo
```

## API principal

Ver tabela completa em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Endpoint | Descrição |
|----------|-----------|
| `GET /api/leads` | Lista leads |
| `GET /api/leads/{domain}` | Workspace |
| `POST /api/leads/{domain}/diagnosis` | Mini diagnóstico |
| `POST /api/leads/{domain}/prototype` | Gerar protótipo |
| `GET /api/diagnoses`, `/api/prototypes` | Histórico global |
| `GET /api/leads/export/csv` | Export comercial (21 colunas) |

## Supabase

**Instalação rápida:** execute [`supabase/migrations/apply_all_v32.sql`](supabase/migrations/apply_all_v32.sql) no SQL Editor.

Detalhes: [`supabase/migrations/README.md`](supabase/migrations/README.md)

Teste manual completo: [`docs/E2E_CHECKLIST.md`](docs/E2E_CHECKLIST.md)

## Lighthouse

Módulo preparado em `parser/lighthouse.py` — **não integrado ao score** nesta fase. Ver [docs/ROADMAP.md](docs/ROADMAP.md).
