"""
Job mensal de cálculo de métricas -- task_events -> metric_snapshots
------------------------------------------------------------------------
Lê os eventos de task_events (Camada 1) e calcula as 9 métricas do
"Grupo 1" (as que têm fórmula clara no documento do chefe e fonte 100%
em task_events) para um projeto e período (mês), gravando um snapshot
novo em metric_snapshots (Camada 3) -- nunca sobrescreve.

Um recálculo do mesmo mês gera OUTRO snapshot, com computed_at mais
recente; o painel sempre lê o mais recente por (metric_key, project, period).

Instalação:
    pip install asyncpg

Configuração (variável de ambiente):
    $env:METRICS_DB_DSN = "postgresql://otel_writer:SUA_SENHA@localhost:5432/metrics_db"

Rodar (mês atual):
    python calcular_metric_snapshots.py team-dados

Rodar pra um mês específico:
    python calcular_metric_snapshots.py team-dados 2026-07
"""

import asyncio
import hashlib
import os
import sys
from calendar import monthrange
from datetime import datetime, timezone

import asyncpg

DB_DSN = os.environ["METRICS_DB_DSN"]
FORMULA_VERSION = 1

# work_item_type e priority reconhecidos pelo catálogo -- se aparecer um
# valor fora dessas listas (ex: um tipo novo do Azure ainda não mapeado),
# pulamos com aviso em vez de estourar a foreign key do metric_snapshots.
TIPOS_CONHECIDOS = {"bug", "pbi", "task", "tech_debt", "feature"}
PRIORIDADES_CONHECIDAS = {"expedite", "alta", "media", "baixa"}


def _periodo_para_intervalo(period: str):
    ano, mes = map(int, period.split("-"))
    inicio = datetime(ano, mes, 1, tzinfo=timezone.utc)
    ultimo_dia = monthrange(ano, mes)[1]
    fim = datetime(ano, mes, ultimo_dia, 23, 59, 59, tzinfo=timezone.utc)
    return inicio, fim


def _snapshot_id(metric_key: str, project: str, period: str) -> str:
    base = f"{metric_key}|{project}|{period}|{datetime.now(timezone.utc).isoformat()}"
    return hashlib.sha256(base.encode()).hexdigest()


async def _gravar_snapshot(conn, metric_key, project, period, value):
    if value is None:
        print(f"  [{metric_key}] sem dados suficientes no período, pulando.")
        return
    snapshot_id = _snapshot_id(metric_key, project, period)
    await conn.execute(
        """
        INSERT INTO metric_snapshots (snapshot_id, metric_key, project, period, value, formula_version)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        snapshot_id, metric_key, project, period, value, FORMULA_VERSION,
    )
    print(f"  [{metric_key}] = {value} (snapshot_id={snapshot_id[:12]}...)")


# ============================================================
# Métricas do Grupo 1 -- uma função por métrica, cada uma
# retornando o valor já calculado (ou None se não houver dados).
# ============================================================

async def pct_entregas_evolutivas(conn, project, inicio, fim):
    row = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE value_tag IN ('evolucao','integracoes','nova_funcionalidade')) AS evolutivas,
          COUNT(*) AS total
        FROM task_events
        WHERE project = $1 AND event_type = 'done' AND occurred_at BETWEEN $2 AND $3
        """,
        project, inicio, fim,
    )
    if not row or row["total"] == 0:
        return None
    return round(100.0 * row["evolutivas"] / row["total"], 2)


async def lead_time_medio(conn, project, inicio, fim):
    row = await conn.fetchrow(
        """
        SELECT AVG(EXTRACT(EPOCH FROM (d.occurred_at - c.occurred_at)) / 86400.0) AS dias
        FROM task_events d
        JOIN task_events c
          ON c.task_id = d.task_id AND c.project = d.project AND c.source = d.source
          AND c.event_type = 'created'
        WHERE d.project = $1 AND d.event_type = 'done' AND d.occurred_at BETWEEN $2 AND $3
        """,
        project, inicio, fim,
    )
    return round(row["dias"], 2) if row and row["dias"] is not None else None


async def cycle_time_medio(conn, project, inicio, fim):
    row = await conn.fetchrow(
        """
        WITH primeiro_andamento AS (
          SELECT task_id, source, MIN(occurred_at) AS inicio_andamento
          FROM task_events
          WHERE project = $1 AND to_status = 'em_andamento'
          GROUP BY task_id, source
        )
        SELECT AVG(EXTRACT(EPOCH FROM (d.occurred_at - a.inicio_andamento)) / 86400.0) AS dias
        FROM task_events d
        JOIN primeiro_andamento a ON a.task_id = d.task_id AND a.source = d.source
        WHERE d.project = $1 AND d.event_type = 'done' AND d.occurred_at BETWEEN $2 AND $3
        """,
        project, inicio, fim,
    )
    return round(row["dias"], 2) if row and row["dias"] is not None else None


async def retrabalho(conn, project, inicio, fim):
    row = await conn.fetchrow(
        """
        WITH passou_validacao AS (
          SELECT task_id, source, MIN(occurred_at) AS quando
          FROM task_events
          WHERE project = $1 AND to_status = 'em_validacao'
          GROUP BY task_id, source
        )
        SELECT COUNT(*) AS total
        FROM task_events t
        JOIN passou_validacao v
          ON v.task_id = t.task_id AND v.source = t.source AND v.quando < t.occurred_at
        WHERE t.project = $1 AND t.event_type = 'status_changed' AND t.to_status = 'em_andamento'
          AND t.occurred_at BETWEEN $2 AND $3
        """,
        project, inicio, fim,
    )
    return row["total"] if row else 0


async def pbi_tested_ratio(conn, project, inicio, fim):
    row = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE tested = true) AS testados,
          COUNT(*) AS total
        FROM task_events
        WHERE project = $1 AND work_item_type = 'pbi' AND event_type = 'done'
          AND occurred_at BETWEEN $2 AND $3
        """,
        project, inicio, fim,
    )
    if not row or row["total"] == 0:
        return None
    return round(100.0 * row["testados"] / row["total"], 2)


async def bugs_x_pbis(conn, project, inicio, fim):
    row = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE work_item_type = 'bug') AS bugs,
          COUNT(*) FILTER (WHERE work_item_type = 'pbi') AS pbis
        FROM task_events
        WHERE project = $1 AND event_type = 'created' AND occurred_at BETWEEN $2 AND $3
        """,
        project, inicio, fim,
    )
    if not row or not row["pbis"]:
        return None
    return round(100.0 * row["bugs"] / row["pbis"], 2)


async def falhas_evitadas(conn, project, inicio, fim):
    row = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE environment_found = 'staging') AS evitadas,
          COUNT(*) AS total
        FROM task_events
        WHERE project = $1 AND work_item_type = 'bug' AND environment_found IS NOT NULL
          AND occurred_at BETWEEN $2 AND $3
        """,
        project, inicio, fim,
    )
    if not row or row["total"] == 0:
        return None
    return round(100.0 * row["evitadas"] / row["total"], 2)


async def itens_por_tipo(conn, project, fim):
    """'Foto' do backlog atual (estado de cada tarefa na data de corte
    'fim'), agrupado por work_item_type -- por isso usa só 'fim', não um
    intervalo: reflete o ESTADO no fim do período, não os eventos dele."""
    rows = await conn.fetch(
        """
        WITH ultimo_estado AS (
          SELECT DISTINCT ON (source, task_id) task_id, source, work_item_type, status
          FROM task_events
          WHERE project = $1 AND occurred_at <= $2
          ORDER BY source, task_id, occurred_at DESC
        )
        SELECT work_item_type, COUNT(*) AS total
        FROM ultimo_estado
        WHERE work_item_type IS NOT NULL
        GROUP BY work_item_type
        """,
        project, fim,
    )
    return {r["work_item_type"]: r["total"] for r in rows}


async def backlog_por_prioridade(conn, project, fim):
    """Mesma lógica de 'foto do estado atual', filtrando status='backlog'
    e agrupando por priority."""
    rows = await conn.fetch(
        """
        WITH ultimo_estado AS (
          SELECT DISTINCT ON (source, task_id) task_id, source, status, priority
          FROM task_events
          WHERE project = $1 AND occurred_at <= $2
          ORDER BY source, task_id, occurred_at DESC
        )
        SELECT priority, COUNT(*) AS total
        FROM ultimo_estado
        WHERE status = 'backlog' AND priority IS NOT NULL
        GROUP BY priority
        """,
        project, fim,
    )
    return {r["priority"]: r["total"] for r in rows}


async def main():
    if len(sys.argv) < 2:
        print("Uso: python calcular_metric_snapshots.py <project> [YYYY-MM]")
        print("Exemplo: python calcular_metric_snapshots.py team-dados 2026-07")
        sys.exit(1)

    project = sys.argv[1]
    period = sys.argv[2] if len(sys.argv) > 2 else datetime.now(timezone.utc).strftime("%Y-%m")
    inicio, fim = _periodo_para_intervalo(period)

    print(f"Calculando métricas para project={project}, period={period} ({inicio.date()} a {fim.date()})")

    conn = await asyncpg.connect(dsn=DB_DSN)
    try:
        await _gravar_snapshot(conn, "pct_entregas_evolutivas", project, period,
                                await pct_entregas_evolutivas(conn, project, inicio, fim))
        await _gravar_snapshot(conn, "lead_time_medio", project, period,
                                await lead_time_medio(conn, project, inicio, fim))
        await _gravar_snapshot(conn, "cycle_time_medio", project, period,
                                await cycle_time_medio(conn, project, inicio, fim))
        await _gravar_snapshot(conn, "retrabalho", project, period,
                                await retrabalho(conn, project, inicio, fim))
        await _gravar_snapshot(conn, "pbi_tested_ratio", project, period,
                                await pbi_tested_ratio(conn, project, inicio, fim))
        await _gravar_snapshot(conn, "bugs_x_pbis", project, period,
                                await bugs_x_pbis(conn, project, inicio, fim))
        await _gravar_snapshot(conn, "falhas_evitadas", project, period,
                                await falhas_evitadas(conn, project, inicio, fim))

        tipos = await itens_por_tipo(conn, project, fim)
        for tipo, total in tipos.items():
            if tipo not in TIPOS_CONHECIDOS:
                print(f"  itens_por_tipo.{tipo}: tipo não cadastrado no metric_catalog, pulando "
                      f"(cadastra lá se quiser rastrear esse tipo).")
                continue
            await _gravar_snapshot(conn, f"itens_por_tipo.{tipo}", project, period, total)

        prioridades = await backlog_por_prioridade(conn, project, fim)
        for prioridade, total in prioridades.items():
            if prioridade not in PRIORIDADES_CONHECIDAS:
                print(f"  backlog_por_prioridade.{prioridade}: prioridade não cadastrada no "
                      f"metric_catalog, pulando.")
                continue
            await _gravar_snapshot(conn, f"backlog_por_prioridade.{prioridade}", project, period, total)
    finally:
        await conn.close()

    print("Concluído.")


if __name__ == "__main__":
    asyncio.run(main())