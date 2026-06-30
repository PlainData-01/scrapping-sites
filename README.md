# scrapping-sites

Agente de scraping e prospecção que analisa sites de clientes, gera briefing, proposta comercial e projeto Next.js personalizado por nicho.

## Requisitos

- Python 3.11+
- Node.js + npm
- [Claude Code CLI](https://github.com/anthropics/claude-code) (opcional, para geração automática do site)

```bash
pip install -r requirements.txt
playwright install chromium
npm install -g @anthropic-ai/claude-code
```

## Configuração

Copie `.env.example` para `.env` e configure sua `ANTHROPIC_API_KEY`.

## Uso

```bash
python agent.py --url https://exemplo.com.br --max-pages 15 --skip-cache
```

O pipeline executa: descoberta de páginas → scraping → análise IA → proposta PDF → briefing → geração do site Next.js via Claude Code CLI.

## Estrutura

- `agent.py` — orquestrador principal
- `crawler/` — descoberta e scraping com Playwright
- `parser/` — parsing HTML e análise com Claude API
- `output/` — briefing, proposta, email e construtor de site
- `storage/` — cache SQLite ou Supabase (multi-usuário)

## Configuração Multi-usuário (Supabase)

Dois usuários podem rodar `python api.py` em máquinas diferentes e compartilhar leads, análises e CRM em tempo real via Supabase (plano gratuito).

### 1. Criar projeto no Supabase (gratuito)

- Acesse: https://supabase.com
- New Project → escolha nome e senha
- Aguarde ~2 minutos

### 2. Criar as tabelas

- Supabase Dashboard → SQL Editor
- **Instalação nova:** cole `supabase/schema.sql` → Run
- **Já rodou o schema antigo?** cole `supabase/migrate_schema.sql` → Run
- Aguarde ~10 segundos (cache do PostgREST recarrega)

### 3. Copiar credenciais

- Settings → API
- Copie: **Project URL** e **service_role** key (secret — não a anon key)
- Cole no `.env`:

```env
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJ...   # service_role, não anon
```

Se preferir usar anon key, execute também `supabase/fix_rls.sql` no SQL Editor.

### 4. Definir seu nome de usuário no `.env`

```env
USUARIO=caio
```

Cada sócio usa o mesmo `SUPABASE_URL` e `SUPABASE_KEY`, mas com `USUARIO` diferente.

### 5. Migrar dados existentes (só na primeira vez)

```bash
python scripts/migrar_para_supabase.py
```

### 6. Rodar normalmente

```bash
python api.py
```

O sistema detecta automaticamente se Supabase está configurado e usa o banco correto. Sem Supabase → SQLite local + arquivos JSON (fallback).
