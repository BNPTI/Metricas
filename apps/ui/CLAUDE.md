# apps/ui — Painel

## App Overview
Frontend que consome os `metric_snapshots` servidos por `apps/api` e apresenta as
métricas (páginas: Evolução, Experiência, Eficiência, Operacional, Desempenho — ver
[reference §6](../../docs/reference/modelo-dados-metricas-bnp.md)). **Não implementado ainda.**

## Tech Stack
A definir quando o painel começar. Ao decidir, habilitar o plugin `bnp-design` em
[.claude/settings.json](../../.claude/settings.json) e atualizar este arquivo.

## Key Invariants
- Consome apenas o read model (`metric_snapshots`), nunca as tabelas brutas.
- Sempre o snapshot mais recente por (`metric_key`, `project`, `period`).

## Playbook
Sem playbook próprio ainda (app não iniciado).
