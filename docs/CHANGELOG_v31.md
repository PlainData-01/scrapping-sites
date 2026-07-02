# Prospect Hub v3.1 — Changelog

## Testado / validado

- [x] Import de `api.py` e módulos novos (`artifact_index`, `lead_utils`, `database`)
- [x] Export CSV com 21 colunas comerciais fixas (`CSV_EXPORT_COLUMNS`)
- [x] Endpoints `GET /api/diagnoses` e `GET /api/prototypes`
- [x] Sincronização de atividades com Supabase (`activities` JSONB) via `_persist_activity`
- [x] Status CRM normalizado (`contacted`, `interested`, etc.) em `update_lead_status`
- [x] `API_BASE_URL` no frontend (`apiUrl()` — relativo quando mesma origem)
- [x] Templates: 3+ variações por nicho (estética, advocacia, restaurante, serviços)
- [ ] Fluxo ponta a ponta com Supabase real (requer `.env` com `SUPABASE_URL` + migration `004_migrate_v31.sql`)
- [ ] Prospecção real Google Maps (requer API key ou Playwright)

## Principais mudanças (v3.1.1)

### P1 — Supabase / persistência
- `storage/database.py` — `append_lead_activity`, `get_lead_activities`, parse JSON robusto
- `status_crm` normalizado no upsert; timestamps `last_contacted_at` / `next_follow_up_at`
- Atividades gravadas no Supabase e mescladas com JSON local no workspace
- Registro de artefatos ao gerar diagnóstico/protótipo (`artifact_index`)

### P2 — Histórico global
- Views **Diagnósticos** e **Protótipos** na sidebar
- `storage/artifact_index.py` — índice JSON + scan de `output/diagnoses` e `output/sites`

### P3 — Nichos
- Estética: `premium_transformacao`, `humanizada`, `procedimento_rapido`
- Advocacia: `autoridade_institucional`, `captacao_area`, `escritorio_local`
- Restaurante: `experiencia_gastronomica`, `delivery_cardapio`, `reservas_eventos`
- Serviços: `orcamento_rapido`, `emergencia_rapidez`, `confianca_local`

### P4 — Export CSV
- Colunas fixas via `lead_to_export_row()` em `storage/lead_utils.py`

### P5 — API_BASE_URL
- `GET /api/env` + prefixo condicional em `app.js` (`apiUrl`)

### P6 — Limpeza
- Removido `START.md` obsoleto (conteúdo consolidado no README)
- Removido `ActivityUpdate` duplicado em `api.py`

### P7 — Lighthouse
- Módulo `parser/lighthouse.py` permanece **preparado, não integrado** ao score principal
- Ativar apenas com `ENABLE_LIGHTHOUSE=true` + `PAGESPEED_API_KEY` (fase posterior)

## Migrations Supabase

Ordem recomendada:

1. `supabase/migrations/001_schema.sql`
2. `supabase/migrations/003_migrate_prospect_hub.sql`
3. `supabase/migrations/004_migrate_v31.sql` — colunas `activities`, `last_contacted_at`, `next_follow_up_at`

## Pendências restantes

- Teste E2E manual com Supabase configurado (prospectar → workspace → reload)
- Lighthouse no pipeline de scoring
- PDF do mini diagnóstico
- Tela de edição de ICPs na UI
- Análise avulsa (`agent.py`) na nova interface
