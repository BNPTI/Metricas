# Infraestrutura — Visão Geral

## Estado atual
Sem IaC. O protótipo roda **localmente** na máquina de desenvolvimento, exposto via
**ngrok** (URL pública instável). Ver [runbook de operação local](../../runbooks/operations/operar-prototipo-local.md).

## Alvo
Antes de uso produtivo, migrar o receiver OTLP e os adapters de webhook para um
servidor com disponibilidade contínua (ex.: VM Azure), com URL pública estável e
validação HMAC do webhook. Definições Terraform entram em `platform/iac/terraform/`
quando essa migração for planejada — hoje não há recursos declarados.
