# Arquitetura — Prospect Hub v3.1

Visão da estrutura do repositório, fluxos principais e o que é código vs. artefato gerado.

## Árvore de pastas

```
scraping-agent/
├── api.py                 # Entry point web — FastAPI + UI Prospect Hub
├── agent.py               # Entry point CLI — scraping/análise avulsa
├── config.py              # Config global (.env, SiteData, OUTPUT_DIR)
├── requirements.txt
│
├── config/
│   └── icps/              # YAML por nicho (odontologia, estética, etc.)
│
├── models/
│   └── lead_status.py     # Enum e normalização de status CRM
│
├── prospector/            # Pipeline comercial
│   ├── pipeline.py        # Maps → scrape → score → mensagens → persistência
│   ├── google_maps.py
│   ├── scoring.py
│   ├── icp_loader.py
│   ├── message_generator.py
│   ├── whatsapp_writer.py
│   ├── leads_crm.py       # CRM local (fallback sem Supabase)
│   ├── activity_log.py    # Log local de atividades
│   ├── next_best_action.py
│   └── dashboard_ops.py
│
├── parser/
│   ├── html_parser.py
│   ├── ai_analyzer.py
│   ├── commercial_analysis.py
│   └── lighthouse.py      # Preparado; não integrado ao score
│
├── crawler/               # Scraping Playwright/HTTP
│   ├── discover.py
│   ├── scraper.py
│   └── assets.py
│
├── output/                # Geradores (código .py versionado)
│   ├── diagnosis.py
│   ├── site_generator.py
│   ├── template_builder.py
│   ├── site_builder.py    # Claude Code / Next.js
│   ├── site_injector.py
│   ├── briefing_export.py
│   ├── proposal.py
│   ├── email_writer.py
│   └── quality_checklist.py
│
├── storage/
│   ├── database.py        # Supabase + SQLite fallback
│   ├── supabase_client.py
│   ├── artifact_index.py  # Índice diagnósticos/protótipos
│   └── lead_utils.py      # Normalização + export CSV
│
├── templates/
│   ├── index.html         # SPA Prospect Hub
│   ├── assets/            # app.css, app.js
│   ├── prototypes/        # JSON por nicho (template mode)
│   ├── proposal_template.html
│   └── email_template.txt
│
├── supabase/
│   └── migrations/        # SQL incremental (001 → 005)
│
├── scripts/
│   └── migrar_para_supabase.py
│
├── tests/
│   ├── test_site_builder.py
│   └── test_site_injector.py
│
└── docs/
    ├── SETUP.md
    ├── ROADMAP.md
    ├── CHANGELOG_v31.md
    ├── ARCHITECTURE.md
    └── skills/
        └── site-generation.md
```

## Fluxos

### Prospecção comercial (UI)

```
templates/index.html
    → api.py (/prospect, /api/leads, /api/leads/{domain})
    → prospector/pipeline.py
    → crawler/ + parser/
    → storage/database.py (Supabase ou CSV local)
    → output/diagnoses/, output/sites/ (artefatos)
```

### Análise avulsa (CLI)

```
agent.py
    → crawler/ + parser/ai_analyzer.py
    → output/briefing_export.py, proposal.py, site_builder.py
```

### Geração de protótipo

```
POST /api/leads/{domain}/prototype
    → output/site_generator.py
    → output/template_builder.py  (modo template)
    → templates/prototypes/{nicho}/
    → output/sites/{slug}/prototype/index.html
```

## Persistência

| Modo | Leads | Sites | Atividades |
|------|-------|-------|------------|
| Supabase | Tabela `leads` | Tabela `sites` | Coluna `activities` JSONB + log local |
| Local | `output/leads/prospeccao.csv` + `leads_crm.py` | SQLite `storage/scraping.db` | `output/leads/activity.json` |

## Endpoints da API

### Prospect Hub v3.1 (UI atual)

- `GET /` — SPA
- `GET /prospect`, `GET /api/prospect/status`
- `GET /api/dashboard`, `GET /api/leads`, `GET /api/leads/{domain}`
- `POST /api/leads/{domain}/status|nota|activity|diagnosis|prototype`
- `GET /api/diagnoses`, `GET /api/prototypes`
- `GET /api/leads/export/csv`, `GET /api/env`
- `GET /prototype/{slug}`, `GET /diagnosis/{slug}/html|md`

### Legado (`agent.py` / UI antiga)

Mantidos por compatibilidade; **não usados** pela SPA v3.1:

- `GET /run` — SSE do `agent.py`
- `GET /api/history` — lista sites crawleados
- `GET /api/briefing/{domain}`, `/api/prompt/{domain}`, `/api/email/{domain}`

## O que não versionar

Tudo em `output/` exceto módulos `.py` — ver `output/README.md` e `.gitignore`.

## Decisão: sem pasta `backend/`

Os pacotes Python permanecem na raiz para evitar quebrar dezenas de imports (`from prospector...`, `from output...`). A separação lógica está documentada acima.
