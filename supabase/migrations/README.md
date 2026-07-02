# Migrations Supabase — Prospect Hub

## Instalação rápida (recomendado v3.2)

Execute **uma vez** no SQL Editor do projeto Supabase **dedicado ao Prospect Hub**:

```txt
supabase/migrations/apply_all_v32.sql
```

Arquivo consolidado e idempotente (tabelas, colunas comerciais, atividades, RLS).

## Ordem incremental (alternativa)

| Ordem | Arquivo | Quando usar |
|-------|---------|-------------|
| 1 | `001_schema.sql` | Instalação nova (tabelas base) |
| 2 | `002_migrate_schema.sql` | Instalações antigas sem colunas extras |
| 3 | `003_migrate_prospect_hub.sql` | Campos comerciais v3 (ICP, score, messages_pack) |
| 4 | `004_migrate_v31.sql` | Atividades JSONB + timestamps comerciais |
| 5 | `005_fix_rls.sql` | Opcional — desabilita RLS para ferramenta interna |

**Instalação nova:** `apply_all_v32.sql` **ou** 001 → 003 → 004 → 005

**Atualização v3.1 → v3.2:** se já tem 001+003, basta 004 (ou `apply_all_v32.sql`).

## Colunas comerciais validadas (leads)

`status_crm`, `score`, `score_reasons`, `main_pain`, `commercial_angle`, `suggested_offer`, `icp_id`, `messages_pack`, `activities`, `last_contacted_at`, `next_follow_up_at`, `created_at`, `updated_at`

> `artifact_index` é índice JSON local em `output/leads/artifacts_index.json`, não coluna Supabase.

## Status da aplicação (v3.2)

Projeto configurado no `.env`: `lnmguonaqoihqvgujdup` (via `SUPABASE_URL`).

**Aplicar migration automaticamente** (após definir `SUPABASE_DB_PASSWORD` no `.env`):

```bash
python scripts/apply_v32_schema.py
```

Ou cole `apply_all_v32.sql` no SQL Editor do mesmo projeto.

O plugin Supabase do Cursor pode não ter permissão neste projeto — use o script acima ou o SQL Editor.
