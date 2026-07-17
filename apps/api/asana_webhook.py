"""
Webhook do Asana -> OpenTelemetry -> Receiver.py -> task_events
------------------------------------------------------------------
Versão otimizada: reutiliza o MeterProvider entre eventos (em vez de
criar um novo a cada chamada) e roda as requisições HTTP síncronas
em threads separadas, para não travar o loop assíncrono do FastAPI.

Instalação:
    pip install fastapi uvicorn requests asyncpg opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

Antes de rodar, configure o token do Asana como variável de ambiente:
    $env:ASANA_TOKEN = "seu_token_aqui"

Rodar:
    uvicorn Asana_webhook:app --port 8002
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import requests
from fastapi import BackgroundTasks, FastAPI, Request, Response

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

app = FastAPI(title="Asana Webhook Receiver")

RECEIVER_URL = "http://localhost:8000/v1/metrics"
ASANA_TOKEN = os.environ.get("ASANA_TOKEN")
DB_DSN = "postgresql://otel_writer:Minha.senha21@localhost:5432/metrics_db"

CUSTOM_FIELD_PRIORIDADE_GID = "1206474834263632"
CUSTOM_FIELD_PROGRESSO_GID = "1206474834263637"

_hook_secret: str | None = None
pool: Optional[asyncpg.Pool] = None

# Cache de providers por time - criado UMA VEZ por owner_team, reutilizado
# em todos os eventos seguintes (em vez de recriar a cada chamada).
_providers_cache: dict[str, tuple] = {}


@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(dsn=DB_DSN)


@app.on_event("shutdown")
async def shutdown():
    await pool.close()
    for provider, _ in _providers_cache.values():
        provider.shutdown()


def _get_provider_e_counter(owner_team: str):
    """Reaproveita o MeterProvider já criado para esse time, se existir.
    Só cria um novo na primeira vez que esse owner_team aparece."""
    if owner_team not in _providers_cache:
        resource = Resource.create({
            "service.name": f"{owner_team}-asana-webhook",
            "service.owner": owner_team,
            "service.natureza": "produtividade",
        })
        exporter = OTLPMetricExporter(endpoint=RECEIVER_URL)
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=2000)
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        meter = provider.get_meter("asana-webhook.meter")
        counter = meter.create_counter(
            "asana.task_events",
            description="Eventos de tarefas do Asana, no formato task_events",
        )
        _providers_cache[owner_team] = (provider, counter)

    return _providers_cache[owner_team]


def _buscar_custom_fields_tarefa_sync(tarefa_gid: str) -> dict:
    """Versão síncrona (roda em thread separada, ver enviar_evento_otel)."""
    if not tarefa_gid:
        return {"tarefa_nome": "", "tarefa_dono": "", "status_atual": None, "prioridade_atual": None}
    try:
        resp = requests.get(
            f"https://app.asana.com/api/1.0/tasks/{tarefa_gid}",
            headers={"Authorization": f"Bearer {ASANA_TOKEN}"},
            params={"opt_fields": "name,assignee.name,custom_fields"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        status_atual = None
        prioridade_atual = None
        for campo in data.get("custom_fields", []):
            if campo.get("gid") == CUSTOM_FIELD_PROGRESSO_GID:
                enum_value = campo.get("enum_value")
                status_atual = enum_value.get("name") if enum_value else None
            elif campo.get("gid") == CUSTOM_FIELD_PRIORIDADE_GID:
                enum_value = campo.get("enum_value")
                prioridade_atual = enum_value.get("name") if enum_value else None

        return {
            "tarefa_nome": data.get("name", ""),
            "tarefa_dono": (data.get("assignee") or {}).get("name", ""),
            "status_atual": status_atual,
            "prioridade_atual": prioridade_atual,
        }
    except Exception as e:
        print(f"Erro ao buscar detalhes da tarefa {tarefa_gid}: {e}")
        return {"tarefa_nome": "", "tarefa_dono": "", "status_atual": None, "prioridade_atual": None}


def _buscar_nome_usuario_sync(usuario_gid: str) -> str:
    if not usuario_gid:
        return ""
    try:
        resp = requests.get(
            f"https://app.asana.com/api/1.0/users/{usuario_gid}",
            headers={"Authorization": f"Bearer {ASANA_TOKEN}"},
            params={"opt_fields": "name"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("name", "")
    except Exception as e:
        print(f"Erro ao buscar usuário {usuario_gid}: {e}")
        return ""


async def buscar_custom_fields_tarefa(tarefa_gid: str) -> dict:
    """Roda a chamada HTTP síncrona numa thread separada, sem travar o loop."""
    return await asyncio.to_thread(_buscar_custom_fields_tarefa_sync, tarefa_gid)


async def buscar_nome_usuario(usuario_gid: str) -> str:
    return await asyncio.to_thread(_buscar_nome_usuario_sync, usuario_gid)


async def buscar_status_anterior(task_id: str) -> Optional[str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT status FROM task_events
            WHERE task_id = $1 AND status IS NOT NULL
            ORDER BY occurred_at DESC
            LIMIT 1
            """,
            task_id,
        )
    return row["status"] if row else None


def gerar_event_id(source: str, task_id: str, event_type: str, occurred_at: str) -> str:
    base = f"{source}|{task_id}|{event_type}|{occurred_at}"
    return hashlib.sha256(base.encode()).hexdigest()


def enviar_evento_otel(owner_team: str, labels: dict):
    """Agora só ADICIONA ao counter já existente - não cria provider novo."""
    _, counter = _get_provider_e_counter(owner_team)
    counter.add(1, labels)


async def processar_eventos(owner_team: str, eventos: list):
    """Roda em background - o Asana já recebeu a resposta 200 antes disso começar,
    então não há risco de timeout mesmo com muitos eventos acumulados."""
    for evento in eventos:
        acao = evento.get("action", "desconhecida")
        recurso = evento.get("resource", {}) or {}
        tipo_recurso = recurso.get("resource_type", "desconhecido")

        if tipo_recurso != "task":
            continue

        task_id = recurso.get("gid", "")
        campo_alterado = (evento.get("change") or {}).get("field", "")
        editado_por_gid = (evento.get("user") or {}).get("gid", "")
        occurred_at = evento.get("created_at") or datetime.now(timezone.utc).isoformat()

        try:
            editado_por_nome, detalhes = await asyncio.gather(
                buscar_nome_usuario(editado_por_gid),
                buscar_custom_fields_tarefa(task_id),
            )
            status_atual = detalhes["status_atual"]

            status_anterior = await buscar_status_anterior(task_id)

            if acao == "added":
                event_type = "created"
                from_status, to_status = None, status_atual
            elif campo_alterado == "completed":
                event_type = "done"
                from_status, to_status = status_anterior, status_atual
            elif status_atual and status_atual != status_anterior:
                event_type = "status_changed"
                from_status, to_status = status_anterior, status_atual
            else:
                event_type = "changed"
                from_status, to_status = None, status_atual

            event_id = gerar_event_id("asana", task_id, event_type, occurred_at)

            labels = {
                "event_id": event_id,
                "task_id": task_id,
                "event_type": event_type,
                "status": status_atual or "",
                "priority": detalhes["prioridade_atual"] or "",
                "from_status": from_status or "",
                "to_status": to_status or "",
                "tarefa_nome": detalhes["tarefa_nome"],
                "tarefa_dono": detalhes["tarefa_dono"],
                "editado_por_nome": editado_por_nome,
                "occurred_at": occurred_at,
                "payload_json": json.dumps(evento),
            }

            enviar_evento_otel(owner_team, labels)
            print(f"[{owner_team}] {event_type} | tarefa: {detalhes['tarefa_nome']} | status: {from_status} -> {to_status} | priority: {detalhes['prioridade_atual']}")
        except Exception as e:
            print(f"Erro processando evento da tarefa {task_id}: {e}")


@app.post("/webhook/asana/{owner_team}")
async def receber_evento(owner_team: str, request: Request, background_tasks: BackgroundTasks):
    global _hook_secret

    handshake_secret = request.headers.get("X-Hook-Secret")
    if handshake_secret:
        _hook_secret = handshake_secret
        return Response(headers={"X-Hook-Secret": handshake_secret})

    body = await request.json()
    eventos = body.get("events", [])

    # Responde IMEDIATAMENTE ao Asana - o processamento de verdade
    # acontece depois, em background, sem risco de timeout.
    background_tasks.add_task(processar_eventos, owner_team, eventos)

    return {"status": "accepted", "eventos_recebidos": len(eventos), "owner_team": owner_team}
