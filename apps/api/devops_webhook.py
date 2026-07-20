"""
Webhook do Azure DevOps -> OpenTelemetry -> Receiver.py -> task_events
------------------------------------------------------------------------
Espelha a mesma arquitetura do Asana_webhook.py: MeterProvider cacheado
por owner_team, processamento em background (BackgroundTasks) e
idempotência via event_id determinístico.

Diferença principal em relação ao Asana: o Azure DevOps já manda o
work item COMPLETO em resource.fields (quando o Service Hook está
configurado com "Resource details to send: All"), então não precisamos
fazer nenhuma chamada extra à API do Azure para enriquecer o evento.
O from_status/to_status continuam sendo calculados consultando o
próprio histórico da task_events (mesmo princípio do Asana) -- assim
os dois vendors ficam consistentes entre si.

Instalação (se ainda não tiver os pacotes do Asana_webhook.py instalados):
    pip install fastapi uvicorn asyncpg opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

Configuração (variáveis de ambiente -- NUNCA hardcode a senha aqui):
    $env:AZURE_DEVOPS_DB_DSN = "postgresql://otel_writer:SUA_SENHA@localhost:5432/metrics_db"

Rodar (porta sugerida: 8003, já que 8000=Receiver e 8002=Asana):
    uvicorn azure_devops_webhook:app --port 8003

Registro do Service Hook (feito manualmente por enquanto, no portal do
Azure DevOps -> Project Settings -> Service Hooks -> Web Hooks):
    - Trigger: "Work item created" e "Work item updated" (duas subscriptions)
    - Resource details to send: All  <- IMPORTANTE, senão os campos vêm vazios
    - URL: https://<seu-ngrok>.ngrok-free.app/webhook/azure_devops/{owner_team}
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import BackgroundTasks, FastAPI, Request

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

app = FastAPI(title="Azure DevOps Webhook Receiver")

RECEIVER_URL = "http://localhost:8000/v1/metrics"

# Sem valor default hardcoded de propósito: se a env var não existir,
# o programa deve falhar alto em vez de rodar com um segredo exposto
# no próprio arquivo (foi isso que aconteceu com o ASANA_TOKEN/senha
# do banco no Asana_webhook.py).
DB_DSN = os.environ["AZURE_DEVOPS_DB_DSN"]

pool: Optional[asyncpg.Pool] = None

# ---------------------------------------------------------------------------
# Mapa de estados -- levantado a partir do "Processo BNP" no Azure DevOps
# (Bug, Product Backlog Item e Task têm exatamente os mesmos nomes de
# estado nas categorias Proposed/In Progress, então um único mapa serve
# para os três tipos).
# ---------------------------------------------------------------------------
MAPA_STATUS = {
    "New": "backlog",
    "To Do": "backlog",
    "Priorizado": "priorizado",
    "Aprovado": "priorizado",
    "Pronto para desenvolver": "priorizado",
    "Em desenvolvimento": "em_andamento",
    "Revisão de Código (PR)": "em_andamento",
    "In Progress": "em_andamento",
    "Pronto para testes": "em_validacao",
    "Em testes": "em_validacao",
    "Pronto para validação": "em_validacao",
    "Em validação": "em_validacao",
    "Pronto para produção": "em_validacao",
    "Done": "concluido",
}

# Estados que na prática significam "saiu do fluxo", não um status normal.
ESTADOS_REMOVIDOS = {"Removed", "undelivered"}

# work_item_type do Azure -> vocabulário do modelo (bug | pbi | tech_debt | feature | task)
MAPA_WORK_ITEM_TYPE = {
    "Bug": "bug",
    "Product Backlog Item": "pbi",
    "Task": "task",
    "Technical Debt": "tech_debt",
    "Feature": "feature",
}

# Cache de providers por owner_team -- criado uma vez, reaproveitado depois
# (mesmo padrão do Asana_webhook.py).
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
    if owner_team not in _providers_cache:
        resource = Resource.create({
            "service.name": f"{owner_team}-azure-devops-webhook",
            "service.owner": owner_team,
            "service.natureza": "produtividade",
        })
        exporter = OTLPMetricExporter(endpoint=RECEIVER_URL)
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=2000)
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        meter = provider.get_meter("azure-devops-webhook.meter")
        counter = meter.create_counter(
            "azure_devops.task_events",
            description="Eventos de work items do Azure DevOps, no formato task_events",
        )
        _providers_cache[owner_team] = (provider, counter)

    return _providers_cache[owner_team]


def _extrair_nome(campo) -> str:
    """Campos de identidade do Azure DevOps vêm em pelo menos três formatos
    diferentes dependendo do contexto: objeto completo ({"displayName": ...}),
    string "Nome Completo <email@dominio.com>" (formato mais comum dentro de
    resource.revision.fields), ou string simples. Protege contra os três
    formatos e contra None -- o mesmo tipo de defesa que o
    (evento.get('user') or {}) do Asana_webhook.py faz para campos nulos."""
    if not campo:
        return ""
    if isinstance(campo, dict):
        return campo.get("displayName", "") or ""
    texto = str(campo)
    if "<" in texto:
        return texto.split("<")[0].strip()
    return texto


async def buscar_status_anterior(source: str, task_id: str) -> Optional[str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT status FROM task_events
            WHERE source = $1 AND task_id = $2 AND status IS NOT NULL
            ORDER BY occurred_at DESC
            LIMIT 1
            """,
            source,
            task_id,
        )
    return row["status"] if row else None


def gerar_event_id(source: str, task_id: str, event_type: str, occurred_at: str) -> str:
    base = f"{source}|{task_id}|{event_type}|{occurred_at}"
    return hashlib.sha256(base.encode()).hexdigest()


def enviar_evento_otel(owner_team: str, labels: dict):
    _, counter = _get_provider_e_counter(owner_team)
    counter.add(1, labels)


async def processar_evento(owner_team: str, body: dict):
    """Roda em background -- o Azure DevOps já recebeu a resposta 200
    antes disso começar (mesmo motivo do BackgroundTasks no Asana:
    evitar timeout do lado do Azure)."""
    event_type_azure = body.get("eventType", "")
    resource = body.get("resource", {}) or {}

    # IMPORTANTE: a forma do payload muda conforme o tipo de evento.
    #
    # Em "workitem.updated", resource.fields contém só os campos que MUDARAM,
    # cada um como {"oldValue": ..., "newValue": ...} -- e resource.id é o id
    # da própria atualização/revisão, NÃO o id do work item. O snapshot
    # completo e atual do work item (com valores simples, não dicts) fica em
    # resource.revision.fields, e o id de verdade fica em resource.workItemId.
    #
    # Em "workitem.created" (e possivelmente outros sem o wrapper "revision"),
    # resource.fields já É o snapshot completo com valores simples, e
    # resource.id já é o id do work item.
    revision = resource.get("revision")
    if revision:
        campos_atuais = revision.get("fields", {}) or {}
        task_id = str(resource.get("workItemId") or revision.get("id") or resource.get("id") or "")
    else:
        campos_atuais = resource.get("fields", {}) or {}
        task_id = str(resource.get("workItemId") or resource.get("id") or "")

    if not task_id or task_id == "0":
        print(f"Evento do Azure DevOps sem id de work item utilizável, ignorando (eventType={event_type_azure}).")
        return

    work_item_type_azure = campos_atuais.get("System.WorkItemType", "")
    work_item_type = MAPA_WORK_ITEM_TYPE.get(work_item_type_azure, work_item_type_azure.lower() or None)

    estado_azure = campos_atuais.get("System.State", "")
    tarefa_nome = campos_atuais.get("System.Title", "")
    prioridade = campos_atuais.get("Microsoft.VSTS.Common.Priority")
    prioridade = str(prioridade) if prioridade is not None else ""
    tarefa_dono = _extrair_nome(campos_atuais.get("System.AssignedTo"))

    # revisedBy é quem fez ESSA atualização especificamente -- mais preciso
    # que System.ChangedBy quando disponível.
    editado_por_nome = _extrair_nome(resource.get("revisedBy")) or _extrair_nome(campos_atuais.get("System.ChangedBy"))

    occurred_at = campos_atuais.get("System.ChangedDate") or campos_atuais.get("System.CreatedDate") \
        or body.get("createdDate") or datetime.now(timezone.utc).isoformat()

    try:
        status_anterior = await buscar_status_anterior("azure_boards", task_id)

        if estado_azure in ESTADOS_REMOVIDOS:
            event_type = "removed"
            status_atual = None
            from_status, to_status = status_anterior, None
        else:
            status_atual = MAPA_STATUS.get(estado_azure)
            if status_atual is None:
                print(f"Aviso: estado '{estado_azure}' não está no MAPA_STATUS (work item {task_id}). "
                      f"Gravando status=NULL -- revisar o mapa se isso se repetir.")

            if event_type_azure == "workitem.created":
                event_type = "created"
                from_status, to_status = None, status_atual
            elif status_atual == "concluido" and status_anterior != "concluido":
                event_type = "done"
                from_status, to_status = status_anterior, status_atual
            elif status_atual and status_atual != status_anterior:
                event_type = "status_changed"
                from_status, to_status = status_anterior, status_atual
            else:
                event_type = "changed"
                from_status, to_status = None, status_atual

        event_id = gerar_event_id("azure_boards", task_id, event_type, occurred_at)

        labels = {
            "event_id": event_id,
            "task_id": task_id,
            "event_type": event_type,
            "work_item_type": work_item_type or "",
            "status": status_atual or "",
            "priority": prioridade,
            "from_status": from_status or "",
            "to_status": to_status or "",
            "tarefa_nome": tarefa_nome,
            "tarefa_dono": tarefa_dono,
            "editado_por_nome": editado_por_nome,
            "occurred_at": occurred_at,
            "payload_json": json.dumps(body),
        }

        enviar_evento_otel(owner_team, labels)
        print(f"[{owner_team}] {event_type} | work item #{task_id} ({work_item_type}): {tarefa_nome} "
              f"| status: {from_status} -> {to_status} | priority: {prioridade}")
    except Exception as e:
        print(f"Erro processando work item {task_id}: {e}")


@app.post("/webhook/azure_devops/{owner_team}")
async def receber_evento(owner_team: str, request: Request, background_tasks: BackgroundTasks):
    body = await request.json()

    # Diferente do Asana, o Azure DevOps manda UM work item por requisição
    # (não um lote de "events"), então não há loop de eventos aqui --
    # só uma tarefa em background por chamada.
    background_tasks.add_task(processar_evento, owner_team, body)

    return {"status": "accepted", "owner_team": owner_team}