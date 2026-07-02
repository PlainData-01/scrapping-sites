-- Prospect Hub v3.2 — migration consolidada idempotente
-- Cole no SQL Editor do Supabase (projeto dedicado ao Prospect Hub)
-- Ordem: executar este arquivo uma vez em instalação nova ou atualização

-- ═══════════════════════════════════════════════════════════════════
-- 001 — Schema base
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS sites (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    pages_count INTEGER DEFAULT 0,
    assets_count INTEGER DEFAULT 0,
    pages JSONB DEFAULT '[]',
    assets JSONB DEFAULT '[]',
    screenshots JSONB DEFAULT '{}',
    contacts JSONB DEFAULT '{}',
    seo_issues JSONB DEFAULT '[]',
    colors JSONB DEFAULT '[]',
    fonts JSONB DEFAULT '[]',
    analysis JSONB DEFAULT NULL,
    business_name TEXT DEFAULT '',
    business_type TEXT DEFAULT '',
    niche_category TEXT DEFAULT '',
    proposal_pdf_path TEXT DEFAULT '',
    briefing_path TEXT DEFAULT '',
    site_project_path TEXT DEFAULT '',
    email_content JSONB DEFAULT NULL,
    fast_mode BOOLEAN DEFAULT FALSE,
    cache_version TEXT DEFAULT '2.0',
    status TEXT DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS leads (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    nome TEXT NOT NULL,
    domain TEXT NOT NULL UNIQUE,
    website TEXT NOT NULL,
    endereco TEXT DEFAULT '',
    telefone TEXT DEFAULT '',
    whatsapp TEXT DEFAULT '',
    whatsapp_link TEXT DEFAULT '',
    google_maps_url TEXT DEFAULT '',
    avaliacao FLOAT DEFAULT 0,
    total_avaliacoes INTEGER DEFAULT 0,
    categoria TEXT DEFAULT '',
    score INTEGER DEFAULT 0,
    plataforma TEXT DEFAULT 'desconhecida',
    prioridade TEXT DEFAULT 'baixa',
    qualificado BOOLEAN DEFAULT TRUE,
    motivo_descarte TEXT DEFAULT '',
    problema_principal TEXT DEFAULT '',
    mensagem_whatsapp TEXT DEFAULT '',
    mensagem_completa TEXT DEFAULT '',
    status_crm TEXT DEFAULT 'new',
    notas JSONB DEFAULT '[]',
    abordado_em TIMESTAMPTZ DEFAULT NULL,
    interessado_em TIMESTAMPTZ DEFAULT NULL,
    fechado_em TIMESTAMPTZ DEFAULT NULL,
    status_processamento TEXT DEFAULT 'pronto',
    site_id BIGINT REFERENCES sites(id) ON DELETE SET NULL,
    prospectado_por TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sites_domain ON sites(domain);
CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status_crm);
CREATE INDEX IF NOT EXISTS idx_leads_prioridade ON leads(prioridade);

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

-- ═══════════════════════════════════════════════════════════════════
-- 002 — Colunas legadas / compatibilidade
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE sites ADD COLUMN IF NOT EXISTS pages JSONB DEFAULT '[]';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS assets JSONB DEFAULT '[]';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS screenshots JSONB DEFAULT '{}';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'completed';

ALTER TABLE leads ADD COLUMN IF NOT EXISTS notas JSONB DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS status_processamento TEXT DEFAULT 'pronto';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS prospectado_por TEXT DEFAULT '';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'leads_domain_key'
    ) THEN
        ALTER TABLE leads ADD CONSTRAINT leads_domain_key UNIQUE (domain);
    END IF;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ═══════════════════════════════════════════════════════════════════
-- 003 — Campos comerciais v3
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE leads ADD COLUMN IF NOT EXISTS icp_id TEXT DEFAULT 'odontologia';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS score_reasons JSONB DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS main_pain TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS commercial_angle TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS suggested_offer TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS commercial_analysis JSONB DEFAULT '{}';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS messages_pack JSONB DEFAULT '{}';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS lighthouse_scores JSONB DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_icp ON leads(icp_id);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score DESC);

-- ═══════════════════════════════════════════════════════════════════
-- 004 — Atividades e timestamps v3.1
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE leads ADD COLUMN IF NOT EXISTS activities JSONB DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_contacted_at TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_follow_up_at TIMESTAMPTZ DEFAULT NULL;

-- Só normaliza status_crm vazio — preserva valores CRM já gravados
UPDATE leads SET status_crm = 'new' WHERE status_crm IS NULL OR status_crm IN ('pendente', '');

-- ═══════════════════════════════════════════════════════════════════
-- 004b — Backfill a partir de colunas legadas (sem apagar dados)
-- ═══════════════════════════════════════════════════════════════════

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'leads' AND column_name = 'status'
    ) THEN
        UPDATE leads
        SET status_processamento = status
        WHERE status IS NOT NULL AND status <> ''
          AND (status_processamento IS NULL OR status_processamento = 'pronto');
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'leads' AND column_name = 'score_detalhes'
    ) THEN
        UPDATE leads
        SET score_reasons = score_detalhes
        WHERE (score_reasons IS NULL OR score_reasons = '[]'::jsonb OR score_reasons = '{}'::jsonb)
          AND score_detalhes IS NOT NULL
          AND jsonb_typeof(score_detalhes) = 'array'
          AND score_detalhes <> '[]'::jsonb;
    END IF;
END $$;

UPDATE leads
SET main_pain = problema_principal
WHERE (main_pain IS NULL OR main_pain = '')
  AND problema_principal IS NOT NULL
  AND problema_principal <> '';

UPDATE leads
SET icp_id = 'odontologia'
WHERE icp_id IS NULL OR icp_id = '';

-- ═══════════════════════════════════════════════════════════════════
-- 005 — RLS desabilitado (ferramenta interna)
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE sites DISABLE ROW LEVEL SECURITY;
ALTER TABLE leads DISABLE ROW LEVEL SECURITY;

NOTIFY pgrst, 'reload schema';

-- ═══════════════════════════════════════════════════════════════════
-- Teste rápido (opcional — descomente para validar)
-- ═══════════════════════════════════════════════════════════════════
/*
INSERT INTO leads (nome, domain, website, score, status_crm, icp_id, main_pain)
VALUES ('Lead Teste PH', 'teste-prospect-hub.local', 'https://teste-prospect-hub.local', 75, 'new', 'odontologia', 'Site desatualizado')
ON CONFLICT (domain) DO UPDATE SET score = EXCLUDED.score;

UPDATE leads SET status_crm = 'contacted', activities = activities || '[{"type":"test","title":"Teste","created_at":"now"}]'::jsonb
WHERE domain = 'teste-prospect-hub.local';

SELECT id, domain, status_crm, score, icp_id, activities FROM leads WHERE domain = 'teste-prospect-hub.local';

DELETE FROM leads WHERE domain = 'teste-prospect-hub.local';
*/
