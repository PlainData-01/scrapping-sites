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
- `storage/` — cache SQLite
