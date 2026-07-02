-- Migração Prospect Hub v3 — campos comerciais explicáveis
-- Executar no SQL Editor se já tiver o schema base

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
