-- Migração: adiciona colunas que faltam se você rodou o schema inicial (prompt v1).
-- Execute no SQL Editor do Supabase ANTES de migrar_para_supabase.py
--
-- Dashboard → SQL Editor → Cole tudo → Run

-- ─── sites ───────────────────────────────────────────────────────
ALTER TABLE sites ADD COLUMN IF NOT EXISTS pages JSONB DEFAULT '[]';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS assets JSONB DEFAULT '[]';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS screenshots JSONB DEFAULT '{}';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'completed';

-- ─── leads ───────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS notas JSONB DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS status_processamento TEXT DEFAULT 'pendente';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS prospectado_por TEXT DEFAULT '';

-- Migrar coluna antiga "nota" (TEXT) → "notas" (JSONB), se existir
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'leads' AND column_name = 'nota'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'leads' AND column_name = 'notas'
    ) THEN
        UPDATE leads
        SET notas = jsonb_build_array(
            jsonb_build_object('texto', nota, 'criado_em', NOW()::text)
        )
        WHERE (notas IS NULL OR notas = '[]'::jsonb)
          AND nota IS NOT NULL AND nota <> '';
    END IF;
END $$;

-- UNIQUE em domain (obrigatório para upsert)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'leads_domain_key'
    ) THEN
        ALTER TABLE leads ADD CONSTRAINT leads_domain_key UNIQUE (domain);
    END IF;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Triggers updated_at (idempotente)
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sites_updated_at ON sites;
DROP TRIGGER IF EXISTS leads_updated_at ON leads;

CREATE TRIGGER sites_updated_at
    BEFORE UPDATE ON sites
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Força PostgREST a recarregar o schema cache
NOTIFY pgrst, 'reload schema';
