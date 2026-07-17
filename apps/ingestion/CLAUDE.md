# apps/ingestion — Camada 1 (Ingestão)

## App Overview
Recebe eventos das fontes (webhooks / OTLP) e grava nas **tabelas brutas** do
TimescaleDB, append-only e idempotente. É o upstream de toda a plataforma.

## Tech Stack
Python 3.13 · FastAPI · OpenTelemetry SDK (OTLP/HTTP Protobuf) · asyncpg · ngrok (dev).

## Directory Map (proposto — código ainda não migrado para cá)
| Caminho | Responsabilidade |
|---|---|
| `receiver/` | Recebedor OTLP: decodifica Protobuf, valida `owner`/natureza, roteia p/ tabela, grava com idempotência |
| `adapters/{fonte}/` | Um adapter por fonte (ex.: `asana`): recebe webhook, enriquece, emite OTLP |
| `schema.sql` | DDL das tabelas brutas (envelope + promovidas) |

> Protótipo atual (`Receiver.py`, `Asana_webhook.py`, `registrar_webhook_asana.py`) descrito em
> [docs/explanation/estado-atual-prototipo.md](../../docs/explanation/estado-atual-prototipo.md).
> Migrar para esta estrutura é trabalho futuro.

## Key Invariants (ver RISK_REGISTER)
- Idempotência por `event_id` determinístico + `ON CONFLICT DO NOTHING` (CI-2).
- Envelope compartilhado completo em toda escrita (CI-3).
- `source` é coluna — nunca criar tabela por vendor (CI-4).
- Responder 200 ao webhook imediatamente; processar em background.

## Auto-documentação
Nova fonte ou nova tabela bruta → atualizar [DOMAIN_MAP](../../docs/ai/PROJECT_DOMAIN_MAP.md)
e o [modelo de dados](../../docs/reference/modelo-dados-metricas-bnp.md).

## Playbook
[Adicionar nova fonte](../../docs/ai/PROJECT_PLAYBOOK.md#playbook-adicionar-nova-fonte)
