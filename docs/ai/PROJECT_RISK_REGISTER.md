# PROJECT_RISK_REGISTER — Base Central de Métricas BNP

> Camada **Governance** (RFC-0001 §4.3). O que a IA **não pode** fazer sem supervisão.
> Carregue este doc antes de QUALQUER alteração de código (Load on Write).

## Critical Invariants

### CI-1 — Append-only estrito
Tabelas brutas (as 7) e `metric_snapshots` **nunca** sofrem UPDATE/DELETE.
- Correção de dado bruto errado = **evento compensatório** (novo evento), nunca edição.
- Correção de métrica = **novo snapshot** versionado, nunca sobrescrita.
- Violação = corrupção de histórico e perda de auditoria/reprodutibilidade.

### CI-2 — Idempotência por event_id
`event_id` é determinístico (id nativo da fonte, ou `SHA-256` de
`source|task_id|event_type|occurred_at`). Ingestão grava com `ON CONFLICT DO NOTHING`.
- Nunca introduzir aleatoriedade ou timestamp de recebimento no hash.
- Mudar a regra do hash quebra a deduplicação de reentregas → duplicação silenciosa.

### CI-3 — Envelope compartilhado obrigatório
Toda tabela bruta carrega as 7 colunas-base (modelo §2). Só as colunas promovidas
mudam por domínio. Não criar tabela bruta sem o envelope completo.

### CI-4 — Agnóstico a vendor
`source` é **coluna**, nunca tabela. Agrupar por natureza do dado. Não criar
`asana_events` / `devops_events` — vai tudo para `task_events` com `source` diferente.

### CI-5 — owner obrigatório no catálogo
Toda linha de `metric_catalog` exige `owner` (NOT NULL). Métrica sem dono não entra.

### CI-6 — Snapshots versionados
`metric_snapshots.formula_version` reflete a versão da definição no catálogo. Recálculo
sempre **anexa** um snapshot novo (`computed_at`), preservando o histórico já calculado.

## State / Transitions (task_events)
Fluxo de `status`: `backlog → priorizado → em_andamento → em_validacao → concluido`.
- **Retrabalho** = regressão para `em_andamento` após `em_validacao` (é métrica, não erro).
- `from_status` **não vem** do evento do Asana — é calculado consultando o último status
  conhecido da `task_id` na própria tabela. Não presumir `from_status` do payload.

## High-Impact Areas (review humano antes de alterar)
| Área | Por quê |
|---|---|
| Geração de `event_id` (ingestão) | Quebra idempotência → duplicação de dados |
| DDL / schema das tabelas brutas | Append-only + envelope + hypertable PK composta |
| Job de cálculo de snapshots (`apps/api`) | Versionamento e reprodutibilidade das métricas |
| `metric_catalog` (definições) | Muda o significado das métricas servidas ao negócio |

## Dependency Risks
- **API do Asana**: `event_type`, `priority`, `status` dependem de custom fields e busca complementar. Custom fields ausentes → colunas NULL (esperado hoje).
- **TimescaleDB**: hypertables exigem PK composta `(event_id, occurred_at)` e GRANTs em `_timescaledb_internal` além do OWNER. Ver [runbook de operação](../../platform/runbooks/operations/operar-prototipo-local.md).
- **opentelemetry-proto**: decodificação Protobuf do OTLP; breaking changes de versão afetam o receiver.

## Technical Debt (protótipo atual)
- Hospedado em máquina de dev; se desligar, a ingestão para. Alvo: servidor com disponibilidade contínua.
- ngrok gratuito troca URL a cada reinício → re-registrar webhook.
- Azure DevOps ainda não migrado para `task_events`.
- `work_item_type`, `value_tag`, `tested`, `environment_found` ficam NULL (sem custom field no Asana).
- Só a Camada 1 existe (parcial). Camadas 2 e 3 não implementadas.

## Security Considerations
- **HMAC do webhook (`X-Hook-Signature`) NÃO validado** — obrigatório antes de produção.
- `ASANA_TOKEN` e credenciais só via env/secret; nunca no repo.
- `payload` bruto pode conter dados pessoais (nomes, respondentes) — tratar como sensível; `respondent_ref` deve ser anonimizado.
