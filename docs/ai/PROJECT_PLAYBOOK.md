# PROJECT_PLAYBOOK — Base Central de Métricas BNP

> Camada **Operational** (RFC-0001 §4.3). Procedimentos por tarefa-tipo.
> **Presença obrigatória, conteúdo evolutivo** — cresce conforme padrões aparecem.
> Antes de qualquer procedimento, carregue o [RISK_REGISTER](PROJECT_RISK_REGISTER.md).

## Índice de tarefas-tipo
- [Adicionar nova fonte de eventos](#playbook-adicionar-nova-fonte) ✅
- [Adicionar métrica ao catálogo](#playbook-adicionar-métrica-ao-catálogo) ✅
- [Adicionar/estender tabela bruta](#playbook-adicionarestender-tabela-bruta) 🚧
- [Implementar job de snapshot mensal](#playbook-job-de-snapshot) 🚧
- [Debug de ingestão](#playbook-debug-de-ingestão) 🚧
- Operação (rodar local, registrar webhook, banco) → [platform/runbooks/](../../platform/runbooks/)

---

## Playbook: Adicionar nova fonte
Ingerir eventos de uma ferramenta nova **sem criar tabela nova** (agnóstico a vendor).

### Pré-condições
- [ ] RISK_REGISTER lido (CI-2 idempotência, CI-3 envelope, CI-4 agnóstico)
- [ ] Definida a **natureza do dado** → qual das 7 tabelas recebe (DOMAIN_MAP)

### Steps
1. Em `apps/ingestion/`, criar o adapter da fonte (recebe webhook / emite OTLP).
2. Mapear os campos da fonte para o **envelope** + colunas promovidas da tabela alvo.
3. Definir `source` (slug da ferramenta) e a regra de `event_id` determinístico.
4. Garantir `ON CONFLICT DO NOTHING` na escrita.
5. Se a fonte reentrega eventos, testar idempotência (mesmo evento 2× → 1 linha).

### Checklist pós-execução
- [ ] Nenhuma tabela nova criada por vendor (usou `source`)
- [ ] `event_id` determinístico e testado contra reentrega
- [ ] Envelope completo preenchido
- [ ] Natureza do dado nova (não cabe nas 7) → atualizar DOMAIN_MAP e reference

---

## Playbook: Adicionar métrica ao catálogo
Declarar uma métrica derivada (Camada 2) **sem escrever código de ingestão**.

### Pré-condições
- [ ] Métrica tem **owner** definido (CI-5)
- [ ] Fonte da métrica é uma das 7 tabelas (DOMAIN_MAP)

### Steps
1. Inserir linha em `metric_catalog` com: `metric_key`, `title`, `scope` (global/product),
   `source_table`, `event_filter` (JSONB), `aggregation`, `unit`, `owner`, `theory_ref`,
   `maturity_bands`.
2. Para `aggregation = ratio`, preencher `ratio_of` (metric_key do denominador).
3. Validar o filtro contra dados reais da `source_table`.
4. Mudou a definição de uma métrica já existente → incrementar `formula_version`
   (os snapshots seguintes registram a nova versão; histórico preservado — CI-6).

### Checklist pós-execução
- [ ] `owner` preenchido
- [ ] `source_table` é uma das 7
- [ ] Mudança de definição → `formula_version` novo, sem editar snapshots antigos

---

## Playbook: Adicionar/estender tabela bruta 🚧
Esboço — preencher quando a primeira tabela nova (além de `task_events`) for criada.
Regras fixas: envelope completo (CI-3), `create_hypertable(..., 'occurred_at')`, PK
composta `(event_id, occurred_at)`, índice `(project, occurred_at DESC)`.

## Playbook: Job de snapshot 🚧
Esboço — preencher ao implementar a Camada 3. Job mensal lê brutas + catálogo, calcula,
**anexa** snapshot versionado. Nunca sobrescreve (CI-1, CI-6).

## Playbook: Debug de ingestão 🚧
Esboço — logs do receiver/adapter, verificar `event_id` duplicado, checar GRANTs do
TimescaleDB. Ver [runbook de operação](../../platform/runbooks/operations/operar-prototipo-local.md).
