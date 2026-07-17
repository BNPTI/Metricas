# PROJECT_DOMAIN_MAP — Base Central de Métricas BNP

> Camada **Semantic** (RFC-0001 §4.3). Linguagem ubíqua e fronteiras de domínio.
> Fonte canônica do DDL e da semântica: [../reference/modelo-dados-metricas-bnp.md](../reference/modelo-dados-metricas-bnp.md).

## Ubiquitous Language
| Termo | Definição |
|---|---|
| **Evento** (grão lifecycle) | Fato discreto e imutável (ex.: `created`, `done`). Correlacionados por chave (ex.: `task_id`) para derivar métricas de duração. |
| **Medição** (grão sample) | Amostra periódica já agregada pela fonte (ex.: sessões/dia). Colunas `metric_key` + `value` + `window`. |
| **Envelope compartilhado** | As 7 colunas-base de toda tabela bruta: `event_id, source, project, occurred_at, ingested_at, schema_version, payload`. |
| **event_id** | Chave de idempotência. Id nativo da fonte, ou hash determinístico de `(source, external_id/task_id, event_type, occurred_at)`. |
| **source** | Ferramenta/produto concreto (`asana`, `azure_boards`...). Coluna, nunca tabela — o modelo é agnóstico a vendor. |
| **project** | Chave canônica do projeto/produto. Dimensão que **toda** métrica filtra. |
| **Append-only** | Sem UPDATE/DELETE. Correção = evento compensatório (bruto) ou novo snapshot (read model). |
| **Evento compensatório** | Novo evento que corrige um anterior sem editar a linha original. |
| **metric_catalog** | Camada semântica: declara como cada métrica sai das brutas (filtro, agregação, owner, bandas de maturidade). Configuração viva (não append-only), mas versiona `formula_version`. |
| **metric_snapshots** | Read model append-only: valores mensais já calculados que o painel consome. Versionado por `formula_version`. |
| **owner** | Responsável por uma métrica/projeto. Obrigatório no catálogo. |
| **maturity_bands** | Faixas (alta/adequado/atenção/crítico) que classificam o valor de uma métrica. |
| **Lead time / Cycle time / MTTA / MTTR / NPS** | Métricas derivadas — fórmulas na reference §3. |
| **Retrabalho** | `status_changed` cujo `to_status` regride para `em_andamento` após já ter passado por `em_validacao`. |
| **hypertable** | Tabela TimescaleDB particionada por `occurred_at`. Exige PK composta incluindo a partition key. |

## Bounded Contexts
Cada tabela bruta é um contexto por **natureza do dado** (não por ferramenta):

| Contexto | Tabela | Grão | Fontes típicas |
|---|---|---|---|
| Gestão de trabalho | `task_events` | evento | Asana, Azure Boards, GitHub, Jira |
| Entrega contínua | `deployment_events` | evento | Azure Pipelines, GitHub Actions |
| Suporte / operação | `ticket_events` | evento | Milvus, Zendesk, JSM |
| Experiência / pesquisa | `survey_responses` | evento | Forms, Typeform |
| Analytics de produto | `usage_samples` | medição | Clarity, GA4, DB dos produtos |
| Desempenho / observabilidade | `performance_samples` | medição | Clarity, Lighthouse, Datadog |
| Negócio por produto (extensão) | `business_events` | evento | o próprio produto |
| Semântica | `metric_catalog` | — | configuração (PO/negócio) |
| Read model | `metric_snapshots` | — | job mensal |

## Context Relationships
- Ingestão (`apps/ingestion`) é **upstream** de todos os contextos brutos: escreve, nunca lê para derivar.
- `metric_catalog` referencia `source_table` (uma das 7) — **downstream** das tabelas brutas.
- `metric_snapshots` é **downstream** de brutas + catálogo (FK `metric_key → metric_catalog`).
- Painel é **downstream** de `metric_snapshots` (lê sempre o snapshot mais recente por `metric_key, project, period`).

## Extensão por produto
`business_events` tem colunas deliberadamente genéricas (`event_name`, `entity_id`,
`value`, `payload`). A semântica de cada métrica de produto vive no **catálogo**, não em
colunas novas — é assim que se pluga uma métrica de produto novo sem alterar schema.

## Pontos em aberto (ver reference §7)
- Unificar `usage_samples` + `performance_samples` em `measurement_samples` com coluna `domain`?
- Cadastros de usuário: `business_events` (evento) ou `usage_samples` (contagem)?
- Governança do append-only: quem emite evento compensatório e como auditar.
