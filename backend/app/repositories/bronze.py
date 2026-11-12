"""Bronze / 待晋升区 repository.

Rows land here during ingest. Only a successful promotion gate moves them to
``canonical_items`` and flips ``status`` to ``promoted``. A failed gate leaves
rows in ``pending`` with ``failure_reason`` recorded, so no row is silently
dropped.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

_COLUMNS = """
    id, run_id, source_id, business_key, title, price, category,
    event_ts, source_revision, payload_json, disposition, status,
    promotion_id, failure_reason, created_at, promoted_at
"""


def _view(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json"))
    return d


def insert_row(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    source_id: int,
    item: dict[str, Any],
    disposition: str,
) -> None:
    conn.execute(
        """
        INSERT INTO bronze_rows(
            run_id, source_id, business_key, title, price, category,
            event_ts, source_revision, payload_json, disposition, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?, 'pending')
        """,
        (
            run_id,
            source_id,
            item["business_key"],
            item["title"],
            item["price"],
            item["category"],
            item["event_ts"],
            item["source_revision"],
            json.dumps(item["payload"], ensure_ascii=False),
            disposition,
        ),
    )


def list_rows(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    run_id: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT {_COLUMNS} FROM bronze_rows {where} ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [_view(r) for r in conn.execute(sql, params).fetchall()]


def list_pending(
    conn: sqlite3.Connection,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    return list_rows(conn, status="pending", run_id=run_id)


def list_by_run(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    """All bronze rows ever recorded for a run (pending + promoted)."""
    return list_rows(conn, run_id=run_id)


def latest_for_key(conn: sqlite3.Connection, business_key: str) -> dict[str, Any] | None:
    """Effective pending row for a business key.

    Picks the newest accepted (not-yet-promoted) state by revision/event time,
    so ingest can compare against it without polluting canonical.
    """
    row = conn.execute(
        f"""
        SELECT {_COLUMNS} FROM bronze_rows
        WHERE business_key = ? AND status = 'pending'
        ORDER BY source_revision DESC, event_ts DESC, id DESC LIMIT 1
        """,
        (business_key,),
    ).fetchone()
    return _view(row) if row else None


def count(conn: sqlite3.Connection, status: str | None = None) -> int:
    if status is None:
        sql = "SELECT COUNT(*) c FROM bronze_rows"
        params: tuple[Any, ...] = ()
    else:
        sql = "SELECT COUNT(*) c FROM bronze_rows WHERE status = ?"
        params = (status,)
    return int(conn.execute(sql, params).fetchone()["c"])


def counts_by_run(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT run_id,
               SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
               SUM(CASE WHEN status = 'promoted' THEN 1 ELSE 0 END) AS promoted_count,
               COUNT(*) AS total_count
        FROM bronze_rows GROUP BY run_id ORDER BY run_id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def mark_promoted(conn: sqlite3.Connection, *, row_ids: list[int], promotion_id: int) -> None:
    if not row_ids:
        return
    placeholders = ",".join("?" for _ in row_ids)
    conn.execute(
        f"""
        UPDATE bronze_rows
        SET status = 'promoted', promotion_id = ?, failure_reason = NULL,
            promoted_at = datetime('now')
        WHERE id IN ({placeholders})
        """,
        (promotion_id, *row_ids),
    )


def mark_failed(
    conn: sqlite3.Connection,
    *,
    row_ids: list[int],
    promotion_id: int,
    reason: str,
) -> None:
    """Keep rows in the pending zone but record why the gate rejected them."""
    if not row_ids:
        return
    placeholders = ",".join("?" for _ in row_ids)
    conn.execute(
        f"""
        UPDATE bronze_rows
        SET status = 'pending', promotion_id = ?, failure_reason = ?
        WHERE id IN ({placeholders})
        """,
        (promotion_id, reason, *row_ids),
    )
