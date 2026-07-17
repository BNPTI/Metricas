# apps/api — Camadas 2 e 3 (Catálogo, Snapshots, Serving)

## App Overview
Declara métricas (`metric_catalog`), calcula os valores mensais (`metric_snapshots` —
job append-only versionado) e expõe a API que o painel consome. **Não implementado
ainda** — este CLAUDE.md fixa a intenção.

## Tech Stack (previsto)
Python 3.13 · FastAPI · asyncpg · TimescaleDB.

## Directory Map (proposto)
| Caminho | Responsabilidade |
|---|---|
| `catalog/` | CRUD/seed de `metric_catalog` (semântica das métricas) |
| `snapshots/` | Job mensal: lê brutas + catálogo → anexa snapshot versionado |
| `serving/` | Endpoints que devolvem o snapshot mais recente por `metric_key, project, period` |

## Key Invariants (ver RISK_REGISTER)
- `metric_snapshots` é append-only e versionado por `formula_version` (CI-1, CI-6).
- `owner` obrigatório no catálogo (CI-5).
- Serving lê sempre o snapshot mais recente por (`metric_key`, `project`, `period`).

## Auto-documentação
Nova métrica ou mudança de definição → atualizar o catálogo e, se muda a linguagem,
[DOMAIN_MAP](../../docs/ai/PROJECT_DOMAIN_MAP.md).

## Playbook
[Adicionar métrica ao catálogo](../../docs/ai/PROJECT_PLAYBOOK.md#playbook-adicionar-métrica-ao-catálogo)
