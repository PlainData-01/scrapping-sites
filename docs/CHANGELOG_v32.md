# Prospect Hub v3.2 — Changelog

Foco: **validação operacional**, correção de atritos e refinamento de UX — sem features grandes novas.

## Testado automaticamente

- [x] Import `api.py` e endpoints principais (`/api/env`, `/api/leads`, `/api/dashboard`, `/api/diagnoses`, `/api/prototypes`)
- [x] `next_best_action` com botões por status
- [x] `artifact_index` com flag `file_exists`

## Testado manualmente (requer `.env` do usuário)

- [ ] Fluxo E2E com Supabase real — ver [`E2E_CHECKLIST.md`](E2E_CHECKLIST.md)
- [ ] Prospecção real Google Maps

## Principais mudanças

### Supabase (Fase 0)

- `supabase/migrations/apply_all_v32.sql` — migration consolidada idempotente
- Documentação atualizada em `supabase/migrations/README.md`
- **Nota:** projetos Supabase existentes na conta não continham tabelas `leads`/`sites` do Prospect Hub — aplicar em projeto dedicado

### UX (Fases 3–7)

- Faixa de onboarding na Visão Geral
- Workspace reorganizado em 6 blocos (resumo, oportunidade, próxima ação, mensagens, produção, histórico)
- Estados vazios e loading em diagnóstico/protótipo/nota/status
- Ações rápidas na lista de leads (copiar, abordar, workspace)
- Filtros: cidade, bairro, plataforma; ordenação: recente, reviews, últimos abordados
- Destaque visual para leads quentes (score, WA, ação pendente)
- Tooltips em botões principais

### Backend

- `next_best_action.py` — CTA principal por status (copiar+abordar, diagnóstico, proposta, etc.)
- `artifact_index.py` — `file_exists` / mensagem quando arquivo físico ausente
- Versão API/UI: **3.2**

### Documentação (Fase 16)

- `docs/E2E_CHECKLIST.md`
- `docs/CHANGELOG_v32.md` (este arquivo)
- README e ROADMAP atualizados

## Não implementado (conforme escopo)

- PDF do diagnóstico
- Chatbot / automação WhatsApp
- Lighthouse no score principal
- Refactor agressivo de pastas Python
- Remoção de endpoints legados

## Pendências

- Aplicar `apply_all_v32.sql` no projeto Supabase dedicado ao Prospect Hub
- Validar E2E com credenciais reais do usuário
- Instalar `pytest` para CI local (`tests/`)
