# Plano de Execução — tasks/

Este diretório hospeda **um** plano de execução por vez, quebrado em tasks pequenas, ordenadas e
**executáveis mecanicamente por um modelo simples (ex.: Haiku)** — cada uma com contexto mínimo,
passos imperativos com **código pronto para transcrever**, critérios de aceite binários e comando de
verificação. O objetivo é que o plano rode **de ponta a ponta via Workflow do Claude, de forma
autônoma**, com o mínimo de autorizações no meio do caminho. As tasks são a unidade de **execução**;
o **PR** agrupa blocos lógicos de tasks relacionadas (ver "Granularidade de PR" abaixo).

> **Nenhuma série ativa.** Este diretório está pronto para a próxima série: crie `PLANO.md` (mestre),
> `00-INDEX.md` (estado) e os arquivos de task por workstream a partir do `_TEMPLATE.md`. Ao concluir
> uma série, mova-a para `docs/archive/tasks-<slug>/` com um `README-ARCHIVE.md` e restaure este aviso.

## O método (como este repositório trabalha)

1. **Planejar primeiro, executar depois.** O Opus (ou o usuário com o Opus) escreve o `PLANO.md`
   mestre e o `_design/` normativo: decisões fechadas, arquitetura-alvo, regras de compatibilidade,
   estratégia de testes. Nada de arquitetura é decidido durante a execução.
2. **Quebrar mecanicamente.** O plano é fatiado em tasks tão pequenas e literais que **Haiku
   consegue executar transcrevendo blocos de código** — sem julgamento de design. Uma task = um
   arquivo; o PR junta um bloco lógico de tasks. Ambiguidade não se resolve na hora: a task vira
   `blocked` com nota.
3. **Executar autônomo + verificar.** As tasks rodam pelo **Workflow do Claude** de forma autônoma:
   um **executor Haiku** transcreve a task, e em seguida um **revisor Opus (adversarial)** confere se
   o resultado bate com o plano e com as invariantes do banco compartilhado.
4. **TDD onde fizer sentido.** Em tasks/planos que envolvem lógica não trivial, **escreva o(s)
   teste(s) primeiro e valide o comportamento ANTES de implementar**. Esse é o **único ponto em que
   parar e confirmar com o usuário é desejado**: alinhe os testes (cenários, casos de borda,
   asserções) com o usuário; assim que usuário e agente concordarem, siga **autônomo** até concluir
   as tasks. Para desenhar/redigir esses testes use o agente **`bnp-quality:qa-strategist`** (análise
   de risco + estratégia de teste). Depois do "de acordo", os testes viram critério de aceite das
   tasks subsequentes.

### Projetando para autonomia (poucas autorizações)

O plano deve correr sozinho. Ao escrever as tasks:

- **Comandos copy-paste, idempotentes**, sem prompts interativos (`-y`/`--non-interactive`; nada de
  `git rebase -i`, `git add -i`).


- **Pontos de parada explícitos e raros**: o único checkpoint humano planejado é a **validação dos
  testes (TDD)** acima. Fora dele, ambiguidade → `blocked`, não pergunta.
- **Pré-aprovar permissões** quando ajudar: ver a skill `fewer-permission-prompts` / `update-config`
  para allowlist em `.claude/settings.json`.

## Estrutura que o próximo plano deve ter

| Arquivo/pasta | O que é |
|---|---|
| `PLANO.md` | Plano mestre (decisões fechadas, arquitetura-alvo, regras de compatibilidade, **estratégia de testes**) |
| `00-INDEX.md` | Tabela mestre de tasks: id, fase, dependências, status. **É o estado do plano** — atualize a cada task concluída (no INDEX **e** no frontmatter da task) |
| `_TEMPLATE.md` | Template padrão de task (já presente neste diretório — use para criar tasks novas) |
| `_design/` | Designs detalhados normativos (entidades, fluxos, trechos do código atual a transcrever) |
| `<WS>-*.md` | Arquivos de task por workstream (ex.: `BE-*`, `FE-*`, `DOC-*`, `I-*`) |

Convenções de id e numeração: prefixo por workstream + número sequencial (`BE-01`, `FE-03`). **Nunca
renumere**; tasks novas entram no fim do workstream. Sufixo de letra para fatiar uma task que cresceu
(`B09a..B09h`). `size`: S (<1h) / M (1–3h) / L (3h+). `phase`: ordem macro dentro do workstream.


## Como executar uma task com um modelo simples

Prompt sugerido por task (executor Haiku):

> Leia e execute a task `tasks/<ID>.md`.
> Siga os passos literalmente, na ordem, transcrevendo os blocos de código como estão. Não tome
> decisões de arquitetura: se algo estiver ambíguo, pare e marque a task como `blocked` com uma nota.
> Ao final, rode o comando de Verificação e cole a saída. Marque os critérios de aceite e
> atualize `00-INDEX.md` (status da task).

Em seguida, um **revisor Opus** confere o diff contra os passos da task, os critérios de aceite e as
invariantes do banco compartilhado (abaixo). Reprovou → corrige ou devolve `blocked`.

Regras que valem para TODAS as tasks (grave-as também em cada arquivo, via `_TEMPLATE.md`):

### Granularidade de PR

A task é a unidade de execução (uma task = um arquivo). **O PR agrupa um bloco lógico de tasks
relacionadas** — aquelas que entregam uma capacidade coerente e fazem sentido revisar/mergear juntas
(ex.: "config + entidades + provider" num PR; "limpeza + remoção de NuGets" em outro). Mantenha o PR
fechado e verde por si só (build/testes passam ao fim do bloco). Commits seguem conventional-commit
referenciando o id da task (`tipo(escopo): descrição [ID]`); o título do PR descreve o bloco.

> Veja `docs/ai/PROJECT_RISK_REGISTER.md` e a raiz `CLAUDE.md` (§6) antes de planejar
