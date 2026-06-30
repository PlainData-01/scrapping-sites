-- Corrige RLS que bloqueia inserts com anon key
-- Execute no SQL Editor do projeto scraping-agent

-- Opcao A (recomendada para ferramenta interna entre 2 socios):
ALTER TABLE sites DISABLE ROW LEVEL SECURITY;
ALTER TABLE leads DISABLE ROW LEVEL SECURITY;

-- Opcao B (alternativa — manter RLS com acesso total via anon):
-- CREATE POLICY "sites_all" ON sites FOR ALL TO anon, authenticated
--   USING (true) WITH CHECK (true);
-- CREATE POLICY "leads_all" ON leads FOR ALL TO anon, authenticated
--   USING (true) WITH CHECK (true);

NOTIFY pgrst, 'reload schema';
