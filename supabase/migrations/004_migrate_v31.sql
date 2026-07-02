-- Prospect Hub v3.1 — atividades e timestamps comerciais
-- Executar após 003_migrate_prospect_hub.sql

ALTER TABLE leads ADD COLUMN IF NOT EXISTS activities JSONB DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_contacted_at TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_follow_up_at TIMESTAMPTZ DEFAULT NULL;

-- Garantir status_crm padrão coerente
UPDATE leads SET status_crm = 'new' WHERE status_crm IS NULL OR status_crm = 'pendente';
