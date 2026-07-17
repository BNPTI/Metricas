# Operar o protótipo local

Subir a ingestão do protótipo (Asana → `task_events`) em ambiente local.

## Pré-requisitos
- PostgreSQL 18 + extensão TimescaleDB
- Python 3.13
- Conta ngrok
- `ASANA_TOKEN` (personal access token) no ambiente

## Dependências
```bash
pip install fastapi uvicorn asyncpg requests opentelemetry-proto opentelemetry-sdk opentelemetry-exporter-otlp-proto-http python-multipart
```

## Banco (TimescaleDB)
Execute o `schema.sql` e configure o usuário de aplicação. **Atenção:** hypertables
guardam chunks em `_timescaledb_internal`, que exige GRANT explícito além do OWNER:
```sql
GRANT USAGE, CREATE ON SCHEMA _timescaledb_internal TO otel_writer;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA _timescaledb_internal TO otel_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA _timescaledb_internal GRANT ALL PRIVILEGES ON TABLES TO otel_writer;
```

## Subir os serviços
```bash
# Terminal 1 — receiver OTLP
uvicorn Receiver:app --port 8000
# Terminal 2 — webhook Asana
uvicorn Asana_webhook:app --port 8002
# Terminal 3 — túnel público
ngrok http 8002
```

## Registrar o webhook no Asana
O Asana não registra webhook pela UI — é via API (`registrar_webhook_asana.py`), com
handshake automático (`X-Hook-Secret`). A URL vem do ngrok; no plano gratuito ela muda
a cada reinício → re-registrar.
