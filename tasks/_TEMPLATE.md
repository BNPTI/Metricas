---
id: XX-00
title: Título imperativo curto
status: todo            # todo | in-progress | blocked | done
depends_on: []          # ids de tasks (ex.: [BE-01, FE-02])
phase: 0                # fase dentro do workstream
size: M                 # S (<1h) | M (1-3h) | L (3h+)
---

# XX-00 — Título

## Contexto mínimo

2–5 linhas: por que a task existe e APENAS o contexto necessário para executá-la sem
explorar o repo inteiro. Links diretos para os arquivos envolvidos.
Ler antes (se aplicável): seções específicas de `_design/...`.

## Regras invioláveis


## Testes primeiro (TDD — quando a task envolve lógica não trivial)

Se aplicável: liste o(s) teste(s) a escrever ANTES da implementação e o comportamento esperado.
Os cenários/asserções devem ter sido acordados com o usuário (apoio do agente `bnp-quality:qa-strategist`)
antes desta task rodar autônoma. Se não aplicável, escreva "n/a".

## Arquivos

| Origem | Destino / Ação |
|---|---|
| caminho/origem | caminho/destino ou "editar" ou "criar" |

## Passos

1. Passo imperativo, único, verificável.
2. ...
   (Nenhum passo pode exigir decisão de arquitetura; se surgir ambiguidade →
   `status: blocked` + nota no 00-INDEX.md.)

## Critérios de aceite

- [ ] Objetivo, binário, verificável por comando ou inspeção.

## Verificação

```bash
# comando literal copy-paste, não interativo
```

## Definition of Done

- [ ] Critérios de aceite verdes
- [ ] Testes (TDD) escritos e passando, quando aplicável
- [ ] Verificação executada com saída colada no PR
- [ ] CI verde (quando existir)
- [ ] docs/ai atualizado se necessário (senão escrever "n/a")
- [ ] `00-INDEX.md`: status desta task → done
- [ ] Commit conventional-commit referenciando o id (ex.: `feat(backend): ... [XX-00]`); a task entra
      no PR do seu bloco lógico (ver "Granularidade de PR" no `README.md`)

## Rollback (apenas quando aplicável — upgrades/deploys)

Comando/procedimento exato para reverter.
