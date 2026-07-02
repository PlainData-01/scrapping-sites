# Checklist E2E — Prospect Hub v3.2

Use este roteiro para validar o fluxo comercial completo com Supabase.

## Pré-requisitos

- [ ] Python 3.11+ e dependências instaladas (`pip install -r requirements.txt`)
- [ ] Playwright Chromium (`playwright install chromium`)
- [ ] Arquivo `.env` configurado a partir de `.env.example`
- [ ] `ANTHROPIC_API_KEY` preenchida (análise comercial)
- [ ] `SUPABASE_URL` e `SUPABASE_KEY` (service role) preenchidos
- [ ] Migrations aplicadas — ver [`supabase/migrations/README.md`](../supabase/migrations/README.md)
  - Instalação nova: `apply_all_v32.sql` **ou** 001 → 003 → 004 → 005
- [ ] `API_BASE_URL=http://127.0.0.1:8000` (padrão local)

## Iniciar

```bash
python api.py
```

Abrir http://127.0.0.1:8000

## Fluxo principal

### Prospecção

- [ ] Escolher ICP **odontologia**
- [ ] Rodar prospecção (busca + cidade)
- [ ] Leads aparecem na lista e no painel
- [ ] Lead salvo no Supabase (verificar tabela `leads`)

### Workspace

- [ ] Abrir workspace de um lead
- [ ] **Bloco 1:** nome, nicho, cidade, contato, site, rating
- [ ] **Bloco 2:** score, `main_pain`, `commercial_angle`, `suggested_offer`, `score_reasons`
- [ ] **Bloco 3:** próxima ação coerente com status
- [ ] **Bloco 4:** mensagens WhatsApp (7 tipos quando disponíveis)

### Ações comerciais

- [ ] Copiar mensagem → toast + atividade `message_copied` no histórico
- [ ] Marcar **abordado** → status `contacted` no Supabase
- [ ] Adicionar nota → persiste em `notas` JSONB
- [ ] Gerar diagnóstico → arquivo em `output/diagnoses/` + índice global
- [ ] Abrir diagnóstico (link HTML)
- [ ] Gerar protótipo → `output/sites/{slug}/prototype/`
- [ ] Abrir protótipo (preview)
- [ ] Copiar link de diagnóstico/protótipo

### Persistência

- [ ] Recarregar página (F5)
- [ ] Lead, status, notas e atividades continuam corretos
- [ ] Workspace reabre consistente

### Export e histórico global

- [ ] Export CSV com 21 colunas comerciais
- [ ] View **Diagnósticos** lista itens gerados
- [ ] View **Protótipos** lista itens gerados
- [ ] Botão workspace a partir do histórico global

## Problemas comuns

| Sintoma | Possível causa |
|---------|----------------|
| Leads não aparecem | Prospecção falhou; Maps/Playwright; sem leads qualificados |
| Erro ao salvar lead | Supabase não configurado; RLS bloqueando; coluna ausente |
| Status não persiste | Migration `004` não aplicada; domain incorreto |
| Atividades vazias após reload | Coluna `activities` ausente; migration v3.1 |
| Diagnóstico não abre | Pasta `output/diagnoses/` gitignored mas deve existir em runtime |
| Protótipo falha | Site não crawleado; rode prospecção completa primeiro |
| RLS bloqueia escrita | Rodar `005_fix_rls.sql` ou `apply_all_v32.sql` |
| Service role no frontend | **Nunca** expor `SUPABASE_SERVICE_ROLE_KEY` na UI — só no `.env` do backend |
| Playwright erro | `playwright install chromium` |
| Maps vazio | Configurar `GOOGLE_MAPS_API_KEY` ou usar Playwright |

## Validação SQL rápida (Supabase)

```sql
SELECT domain, status_crm, score, icp_id, main_pain,
       jsonb_array_length(COALESCE(activities, '[]'::jsonb)) AS n_atividades
FROM leads
ORDER BY updated_at DESC
LIMIT 5;
```

## Fallback local (sem Supabase)

- [ ] Remover ou deixar vazios `SUPABASE_URL` / `SUPABASE_KEY`
- [ ] Prospecção grava em `output/leads/prospeccao.csv`
- [ ] CRM local via `leads_crm.py` + `activity.json`
- [ ] Fluxo da UI continua funcional
