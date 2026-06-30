# Iniciar interface visual

```bash
pip install fastapi "uvicorn[standard]"
python api.py
```

Abrir: http://localhost:8000

## Uso

1. Cole a URL do site no painel central
2. Ajuste o número máximo de páginas (5–50)
3. Clique em **Rodar Agente** (ou `Ctrl+Enter` com o campo URL focado)
4. Acompanhe os logs em tempo real na aba **Logs**
5. Ao concluir, confira **Email**, **Prompt** e **Briefing** nas abas à direita
6. O histórico à esquerda lista execuções anteriores salvas no SQLite

## Prospecção via Google Maps

Na interface web, clique em **🎯 Prospectar** no topo:

1. Informe a busca (ex: `clínica odontológica`) e a cidade
2. Clique em **Buscar e Prospectar**
3. O pipeline busca leads no Google Maps, roda o scraping e gera mensagens WhatsApp
4. Resultados salvos em `output/leads/prospeccao.csv`

Opcional: configure `GOOGLE_MAPS_API_KEY` no `.env` para usar a Places API (mais confiável).

Via terminal:

```bash
python -c "import asyncio; from prospector.pipeline import prospectar; asyncio.run(prospectar(max_leads=3))"
```
