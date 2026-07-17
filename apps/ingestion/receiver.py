"""
Receptor OTLP + CRUD local em Python
--------------------------------------
Recebe métricas no formato OTLP (enviadas pelo SDK do OpenTelemetry)
e grava direto no TimescaleDB. Também expõe endpoints CRUD simples
para consultar/gerenciar os dados.

Instalação:
    pip install fastapi uvicorn asyncpg opentelemetry-proto

Rodar:
    uvicorn Receiver:app --port 8000
"""

import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from pydantic import BaseModel

app = FastAPI(title="OTel -> TimescaleDB Receiver")

DB_DSN = "postgresql://otel_writer:Minha.senha21@localhost:5432/metrics_db"

# Mapeia o valor do atributo "service.natureza" para o nome da tabela genérica.
# Usado para qualquer métrica que NÃO seja tratada de forma especial abaixo.
NATUREZA_TABELAS = {
    "produtividade": "metrics_produtividade",
    # "comercial": "metrics_comercial",
    # "financeiro": "metrics_financeiro",
}

# Nome da métrica que recebe tratamento especial: vai para a tabela
# "task_events" (modelo de dados da BNP), em vez da tabela genérica de natureza.
METRICA_TASK_EVENTS = "asana.task_events"

pool: Optional[asyncpg.Pool] = None


@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(dsn=DB_DSN)


@app.on_event("shutdown")
async def shutdown():
    await pool.close()


def _attrs_to_dict(attrs) -> dict:
    """Converte lista de KeyValue do protobuf em dict Python."""
    result = {}
    for kv in attrs:
        value = kv.value
        if value.HasField("string_value"):
            result[kv.key] = value.string_value
        elif value.HasField("int_value"):
            result[kv.key] = value.int_value
        elif value.HasField("double_value"):
            result[kv.key] = value.double_value
        elif value.HasField("bool_value"):
            result[kv.key] = value.bool_value
    return result


# ============================================================
# ENDPOINT DE INGESTÃO (o "Collector" da sua arquitetura)
# É pra este endpoint que o SDK do OpenTelemetry manda os dados
# ============================================================
@app.post("/v1/metrics")
async def receive_metrics(request: Request):
    body = await request.body()
    req = ExportMetricsServiceRequest()
    req.ParseFromString(body)

    rows_por_tabela: dict[str, list] = {}
    linhas_task_events: list = []

    rejeitadas_sem_owner = 0
    rejeitadas_sem_natureza = 0

    for resource_metrics in req.resource_metrics:
        resource_attrs = _attrs_to_dict(resource_metrics.resource.attributes)
        service_name = resource_attrs.get("service.name", "unknown")
        owner_team = resource_attrs.get("service.owner", "unknown")
        natureza = resource_attrs.get("service.natureza", "unknown")

        if owner_team == "unknown":
            rejeitadas_sem_owner += 1
            continue

        tabela_destino = NATUREZA_TABELAS.get(natureza)
        if tabela_destino is None:
            rejeitadas_sem_natureza += 1
            continue

        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                metric_name = metric.name

                if metric.HasField("sum"):
                    data_points = metric.sum.data_points
                elif metric.HasField("gauge"):
                    data_points = metric.gauge.data_points
                elif metric.HasField("histogram"):
                    for dp in metric.histogram.data_points:
                        ts = datetime.fromtimestamp(dp.time_unix_nano / 1e9, tz=timezone.utc)
                        avg = dp.sum / dp.count if dp.count else 0.0
                        labels = _attrs_to_dict(dp.attributes)
                        linhas = rows_por_tabela.setdefault(tabela_destino, [])
                        linhas.append((ts, metric_name, service_name, owner_team, avg, labels))
                    continue
                else:
                    data_points = []

                for dp in data_points:
                    ts = datetime.fromtimestamp(dp.time_unix_nano / 1e9, tz=timezone.utc)
                    value = dp.as_double if dp.HasField("as_double") else dp.as_int
                    labels = _attrs_to_dict(dp.attributes)

                    # TRATAMENTO ESPECIAL: eventos de tarefa (Asana, e futuramente
                    # DevOps) vão para a tabela task_events, no formato do modelo BNP.
                    if metric_name == METRICA_TASK_EVENTS:
                        occurred_at_str = labels.get("occurred_at", "")
                        try:
                            occurred_at = datetime.fromisoformat(occurred_at_str.replace("Z", "+00:00"))
                        except Exception:
                            occurred_at = ts

                        try:
                            payload = json.loads(labels.get("payload_json", "{}"))
                        except Exception:
                            payload = {}

                        linhas_task_events.append({
                            "event_id": labels.get("event_id", ""),
                            "source": "asana",
                            "project": owner_team,  # por enquanto usamos o time como projeto
                            "occurred_at": occurred_at,
                            "task_id": labels.get("task_id", ""),
                            "event_type": labels.get("event_type", ""),
                            "work_item_type": None,
                            "value_tag": None,
                            "priority": labels.get("priority") or None,
                            "status": labels.get("status") or None,
                            "from_status": labels.get("from_status") or None,
                            "to_status": labels.get("to_status") or None,
                            "tested": None,
                            "environment_found": None,
                            "payload": payload,
                        })
                    else:
                        linhas = rows_por_tabela.setdefault(tabela_destino, [])
                        linhas.append((ts, metric_name, service_name, owner_team, float(value), labels))

    total_inserido = 0

    async with pool.acquire() as conn:
        for tabela, linhas in rows_por_tabela.items():
            await conn.executemany(
                f"""
                INSERT INTO {tabela} (time, metric_name, service_name, owner_team, value, labels)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                [(r[0], r[1], r[2], r[3], r[4], json.dumps(r[5])) for r in linhas],
            )
            total_inserido += len(linhas)

        if linhas_task_events:
            # ON CONFLICT DO NOTHING: se o Asana reentregar o mesmo evento
            # (mesmo event_id), a segunda tentativa é simplesmente ignorada.
            await conn.executemany(
                """
                INSERT INTO task_events (
                    event_id, source, project, occurred_at,
                    task_id, event_type, work_item_type, value_tag,
                    priority, status, from_status, to_status,
                    tested, environment_found, payload
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15::jsonb
                )
                ON CONFLICT (event_id, occurred_at) DO NOTHING
                """,
                [
                    (
                        r["event_id"], r["source"], r["project"], r["occurred_at"],
                        r["task_id"], r["event_type"], r["work_item_type"], r["value_tag"],
                        r["priority"], r["status"], r["from_status"], r["to_status"],
                        r["tested"], r["environment_found"], json.dumps(r["payload"]),
                    )
                    for r in linhas_task_events
                ],
            )
            total_inserido += len(linhas_task_events)

    return {
        "status": "ok",
        "inserted": total_inserido,
        "rejeitadas_sem_owner": rejeitadas_sem_owner,
        "rejeitadas_sem_natureza": rejeitadas_sem_natureza,
    }


# ============================================================
# ENDPOINT MANUAL (JSON simples) - para testar via Postman/navegador
# ============================================================
class ManualMetric(BaseModel):
    metric_name: str
    service_name: str
    owner_team: str
    value: float
    labels: Optional[dict] = None


@app.post("/v1/metrics/manual")
async def receive_metric_manual(metric: ManualMetric):
    if not metric.owner_team:
        raise HTTPException(status_code=400, detail="owner_team é obrigatório")

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO metrics (time, metric_name, service_name, owner_team, value, labels)
            VALUES (now(), $1, $2, $3, $4, $5::jsonb)
            """,
            metric.metric_name,
            metric.service_name,
            metric.owner_team,
            metric.value,
            json.dumps(metric.labels or {}),
        )
    return {"status": "ok", "inserted": 1}


# ============================================================
# CRUD - Consulta de task_events (Read)
# ============================================================
@app.get("/task-events")
async def list_task_events(project: Optional[str] = None, task_id: Optional[str] = None, limit: int = 100):
    query = "SELECT * FROM task_events WHERE 1=1"
    params = []
    if project:
        params.append(project)
        query += f" AND project = ${len(params)}"
    if task_id:
        params.append(task_id)
        query += f" AND task_id = ${len(params)}"
    query += f" ORDER BY occurred_at DESC LIMIT {limit}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


# ============================================================
# CRUD - Registro de ownership (Create / Read / Update / Delete)
# ============================================================
class RegistryEntry(BaseModel):
    service_name: str
    owner_team: str
    description: Optional[str] = None


@app.post("/registry")
async def create_registry(entry: RegistryEntry):
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO metric_registry (service_name, owner_team, description)
                VALUES ($1, $2, $3)
                RETURNING id, service_name, owner_team, description
                """,
                entry.service_name, entry.owner_team, entry.description,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=409, detail="service_name já registrado")
    return dict(row)


@app.get("/registry")
async def list_registry():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM metric_registry ORDER BY owner_team")
    return [dict(r) for r in rows]