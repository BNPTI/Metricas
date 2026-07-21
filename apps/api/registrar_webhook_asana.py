"""
Registrar Webhooks no Asana (múltiplos projetos)
----------------------------------------------------
Roda esse script sempre que quiser adicionar um projeto novo.
Ele registra (ou re-registra) TODOS os projetos da lista PROJETOS de uma vez.

Antes de rodar:
1. Garanta que o Receiver.py está rodando (porta 8000)
2. Garanta que o asana_webhook.py está rodando (porta 8002)
3. Garanta que o ngrok está rodando, apontando pra porta 8002
4. Preencha ASANA_TOKEN (uma vez só) e URL_NGROK (toda vez que reiniciar o ngrok)
5. Para adicionar um projeto novo: só acrescenta uma linha na lista PROJETOS

Instalação:
    pip install requests
"""

import os

import requests
import os
from dotenv import load_dotenv

load_dotenv()  # lê o arquivo .env e carrega as variáveis

# Preferível: defina a variável de ambiente ASANA_TOKEN em vez de deixar
# a chave escrita aqui no código (evita vazar o token sem querer).
ASANA_TOKEN = os.environ.get("ASANA_TOKEN")

URL_NGROK = "https://serrated-veneering-evasive.ngrok-free.dev"

# ============================================================
# ÚNICA COISA QUE VOCÊ PRECISA EDITAR PARA ADICIONAR UM PROJETO NOVO:
# só acrescenta um item nessa lista, com o gid do projeto e o time dono.
# ============================================================
PROJETOS = [
    {"gid": "1206474834263614", "owner_team": "team-dados"},]


def registrar_projeto(gid: str, owner_team: str):
    target = f"{URL_NGROK}/webhook/asana/{owner_team}"

    resp = requests.post(
        "https://app.asana.com/api/1.0/webhooks",
        headers={"Authorization": f"Bearer {ASANA_TOKEN}"},
        json={"data": {"resource": gid, "target": target}},
    )

    print(f"\n=== Time: {owner_team} | Projeto GID: {gid} ===")
    print("URL de destino:", target)
    print("Status:", resp.status_code)
    print("Resposta:", resp.json())

    if resp.status_code == 201:
        print("Webhook criado com sucesso!")
    else:
        print("Algo deu errado. Confira o token e o GID do projeto.")


if __name__ == "__main__":
    for projeto in PROJETOS:
        registrar_projeto(projeto["gid"], projeto["owner_team"])