-- Schema Supabase para scraping-agent (multi-usuário)
-- Executar no SQL Editor do Supabase Dashboard

-- Tabela principal de sites analisados
CREATE TABLE IF NOT EXISTS sites (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Dados do scraping
    pages_count INTEGER DEFAULT 0,
    assets_count INTEGER DEFAULT 0,
    pages JSONB DEFAULT '[]',
    assets JSONB DEFAULT '[]',
    screenshots JSONB DEFAULT '{}',
    contacts JSONB DEFAULT '{}',
    seo_issues JSONB DEFAULT '[]',
    colors JSONB DEFAULT '[]',
    fonts JSONB DEFAULT '[]',

    -- Análise IA
    analysis JSONB DEFAULT NULL,
    business_name TEXT DEFAULT '',
    business_type TEXT DEFAULT '',
    niche_category TEXT DEFAULT '',

    -- Outputs gerados
    proposal_pdf_path TEXT DEFAULT '',
    briefing_path TEXT DEFAULT '',
    site_project_path TEXT DEFAULT '',
    email_content JSONB DEFAULT NULL,

    -- Modo e cache
    fast_mode BOOLEAN DEFAULT FALSE,
    cache_version TEXT DEFAULT '2.0',
    status TEXT DEFAULT 'completed'
);

-- Tabela de leads da prospecção
CREATE TABLE IF NOT EXISTS leads (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Dados do lead
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

    -- Qualificação automática
    score INTEGER DEFAULT 0,
    plataforma TEXT DEFAULT 'desconhecida',
    prioridade TEXT DEFAULT 'baixa',
    qualificado BOOLEAN DEFAULT TRUE,
    motivo_descarte TEXT DEFAULT '',
    problema_principal TEXT DEFAULT '',

    -- Mensagem gerada
    mensagem_whatsapp TEXT DEFAULT '',
    mensagem_completa TEXT DEFAULT '',

    -- CRM manual
    status_crm TEXT DEFAULT 'pendente',
    notas JSONB DEFAULT '[]',
    abordado_em TIMESTAMPTZ DEFAULT NULL,
    interessado_em TIMESTAMPTZ DEFAULT NULL,
    fechado_em TIMESTAMPTZ DEFAULT NULL,

    status_processamento TEXT DEFAULT 'pendente',

    -- Relacionamento com análise completa
    site_id BIGINT REFERENCES sites(id) ON DELETE SET NULL,

    prospectado_por TEXT DEFAULT ''
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_sites_domain ON sites(domain);
CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status_crm);
CREATE INDEX IF NOT EXISTS idx_leads_prioridade ON leads(prioridade);

-- Trigger para atualizar updated_at automaticamente
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
