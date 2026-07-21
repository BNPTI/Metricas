"""
Registro automático de Service Hooks do Azure DevOps -> devops_webhook.py
---------------------------------------------------------------------------
Equivalente ao registrar_webhook_asana.py, mas para o Azure DevOps: usa a
REST API de Service Hooks (Subscriptions) para criar as assinaturas de
"Work item created" e "Work item updated" automaticamente, apontando pra
URL do ngrok -- sem precisar entrar no portal e escolher o Trigger na mão
(evita o erro que já aconteceu de selecionar "Advanced Security alert"
por engano).

Documentação oficial:
    https://learn.microsoft.com/azure/devops/service-hooks/create-subscription

Instalação:
    pip install requests

Configuração (variável de ambiente -- NUNCA hardcode o PAT aqui):
    $env:AZURE_DEVOPS_PAT = "seu_personal_access_token"

O PAT precisa do escopo "Service Hooks (Read & manage)". Gerar em:
    https://dev.azure.com/bnpdesenvolvimento/_usersSettings/tokens

Rodar (1x por projeto novo, ou toda vez que o ngrok mudar de URL):
    python registrar_service_hook_azure_devops.py <URL_DO_NGROK>

Exemplo:
    python registrar_service_hook_azure_devops.py https://serrated-veneering-evasive.ngrok-free.dev

O script é idempotente: se já existir uma subscription apontando pra
MESMA url, não recria. Se existir uma subscription do mesmo
evento/projeto mas com uma URL ANTIGA (ngrok mudou), remove a antiga
antes de criar a nova -- assim não acumula assinaturas obsoletas,
mesmo problema que o limpar_webhooks_asana.py resolve pro lado do Asana.
"""

import base64
import os
import sys

import requests

ORGANIZATION = "bnpdesenvolvimento"  # dev.azure.com/bnpdesenvolvimento
API_VERSION = "7.1"

# Lista de projetos que devem ter o Service Hook registrado.
# Um item por projeto do Azure DevOps que alimenta a Base Central de Métricas.
PROJETOS = [
    {"nome_projeto": "BNP", "owner_team": "team-dados"},
]

# Eventos que o devops_webhook.py sabe processar (ver processar_evento()).
EVENTOS = ["workitem.created", "workitem.updated"]

PAT = os.environ["AZURE_DEVOPS_PAT"]


def _headers() -> dict:
    token = base64.b64encode(f":{PAT}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def buscar_project_id(nome_projeto: str) -> str:
    url = f"https://dev.azure.com/{ORGANIZATION}/_apis/projects/{nome_projeto}?api-version={API_VERSION}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()["id"]


def listar_subscriptions_existentes() -> list:
    url = f"https://dev.azure.com/{ORGANIZATION}/_apis/hooks/subscriptions?api-version={API_VERSION}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json().get("value", [])


def criar_subscription(event_type: str, project_id: str, webhook_url: str) -> dict:
    url = f"https://dev.azure.com/{ORGANIZATION}/_apis/hooks/subscriptions?api-version={API_VERSION}"
    body = {
        "publisherId": "tfs",
        "eventType": event_type,
        "resourceVersion": "1.0",
        "consumerId": "webHooks",
        "consumerActionId": "httpRequest",
        "publisherInputs": {
            "projectId": project_id,
            # Sem areaPath/workItemType/tag aqui -- pega todos os tipos
            # (Bug, Product Backlog Item, Task, etc.), igual configuramos
            # manualmente na primeira vez.
        },
        "consumerInputs": {
            "url": webhook_url,
            # "all" = manda o snapshot completo em resource.revision.fields
            # (é o que o devops_webhook.py espera -- ver comentário no topo dele).
            "resourceDetailsToSend": "all",
        },
    }
    resp = requests.post(url, headers=_headers(), json=body, timeout=15)
    if not resp.ok:
        print(f"  Erro ao criar subscription: {resp.status_code} - {resp.text}")
        resp.raise_for_status()
    return resp.json()


def remover_subscription(subscription_id: str):
    url = f"https://dev.azure.com/{ORGANIZATION}/_apis/hooks/subscriptions/{subscription_id}?api-version={API_VERSION}"
    resp = requests.delete(url, headers=_headers(), timeout=15)
    resp.raise_for_status()


def main():
    if len(sys.argv) < 2:
        print("Uso: python registrar_service_hook_azure_devops.py <URL_DO_NGROK>")
        print("Exemplo: python registrar_service_hook_azure_devops.py https://serrated-veneering-evasive.ngrok-free.dev")
        sys.exit(1)

    ngrok_base_url = sys.argv[1].rstrip("/")

    subscriptions_existentes = listar_subscriptions_existentes()

    for projeto in PROJETOS:
        nome_projeto = projeto["nome_projeto"]
        owner_team = projeto["owner_team"]
        webhook_url = f"{ngrok_base_url}/webhook/azure_devops/{owner_team}"
        sufixo_rota = f"/webhook/azure_devops/{owner_team}"

        print(f"\n--- Projeto: {nome_projeto} (owner_team={owner_team}) ---")
        project_id = buscar_project_id(nome_projeto)
        print(f"project_id: {project_id}")

        for event_type in EVENTOS:
            # Subscriptions do mesmo evento/projeto que já apontam pra ESSE
            # projeto -- pode já estar certa (mesma URL) ou desatualizada
            # (URL antiga do ngrok).
            candidatas = [
                s for s in subscriptions_existentes
                if s.get("eventType") == event_type
                and s.get("publisherInputs", {}).get("projectId") == project_id
                and sufixo_rota in s.get("consumerInputs", {}).get("url", "")
            ]

            ja_correta = next((s for s in candidatas if s["consumerInputs"]["url"] == webhook_url), None)
            if ja_correta:
                print(f"  [{event_type}] já existe e já aponta pra essa URL (id={ja_correta['id']}), pulando.")
                continue

            for s in candidatas:
                print(f"  [{event_type}] removendo subscription desatualizada "
                      f"(id={s['id']}, url antiga={s['consumerInputs']['url']})")
                remover_subscription(s["id"])

            criada = criar_subscription(event_type, project_id, webhook_url)
            print(f"  [{event_type}] criada (id={criada['id']}) -> {webhook_url}")


if __name__ == "__main__":
    main()