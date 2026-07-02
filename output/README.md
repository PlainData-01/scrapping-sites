# Pasta `output/`

## Código-fonte (versionado)

Módulos Python de geração de artefatos:

- `diagnosis.py` — mini diagnósticos
- `site_generator.py` — orquestrador (template / claude_code / prompt_only)
- `template_builder.py` — protótipos HTML estáticos
- `site_builder.py` — Next.js via Claude Code CLI
- `site_injector.py`, `briefing_export.py` — pipeline legado do `agent.py`
- `proposal.py`, `email_writer.py`, `quality_checklist.py`

## Artefatos gerados (não versionados)

Criados em runtime; listados no `.gitignore`:

| Subpasta | Conteúdo |
|----------|----------|
| `diagnoses/` | Mini diagnósticos por lead (`{slug}/diagnostico.*`) |
| `sites/` | Protótipos e projetos Next.js gerados |
| `leads/` | CSV de prospecção, activity log local, índice de artefatos |
| `briefings/` | Briefings `.md` do `agent.py` |
| `exports/` | Exportações salvas em disco (opcional) |
| `assets/`, `screenshots/` | Cache de scraping |
