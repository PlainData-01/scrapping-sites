# Setup — Prospect Hub

## Requisitos

- Python 3.11+
- Playwright Chromium
- Node.js (opcional — modo `claude_code` do gerador de sites)

```bash
pip install -r requirements.txt
playwright install chromium
```

## Variáveis de ambiente

```bash
cp .env.example .env
```

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `ANTHROPIC_API_KEY` | Sim (análise IA) | API Anthropic |
| `GOOGLE_MAPS_API_KEY` | Não | Places API; sem key usa Playwright |
| `SUPABASE_URL` | Não | Persistência multi-usuário |
| `SUPABASE_KEY` | Não | Service role key |
| `API_BASE_URL` | Não | Default `http://127.0.0.1:8000` |
| `DEFAULT_SITE_GENERATOR_MODE` | Não | `template` (padrão), `claude_code`, `prompt_only` |
| `ENABLE_LIGHTHOUSE` | Não | `true` + `PAGESPEED_API_KEY` (fase posterior) |

## Supabase

1. Crie projeto no [Supabase](https://supabase.com)
2. Execute migrations em ordem — ver [`supabase/migrations/README.md`](../supabase/migrations/README.md)
3. Configure `SUPABASE_URL` e `SUPABASE_KEY` no `.env`

Ordem mínima (instalação nova):

1. `001_schema.sql`
2. `003_migrate_prospect_hub.sql`
3. `004_migrate_v31.sql`

## Rodar

```bash
python api.py
```

Abra http://127.0.0.1:8000

### CLI (análise avulsa)

```bash
python agent.py --url https://exemplo.com.br --max-pages 15 --skip-cache
```

### Migração única para Supabase

```bash
python scripts/migrar_para_supabase.py
```

### Testes

```bash
pytest tests/
```
