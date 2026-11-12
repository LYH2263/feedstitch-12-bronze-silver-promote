"""Promotion batch repository: persisted, refresh-safe promotion reports."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def create_batch(
    conn: sqlite3.Connection,
    *,
    scope: str,
    run_id: int | None,
    candidate_count: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO promotion_batches(scope, run_id, status, candidate_count,
                                      success_count, failure_count, report_json)
        VALUES (?, ?, 'running', ?, 0, 0, '{}')
        """,
        (scope, run_id, candidate_count),
    )
    return int(cur.lastrowid)


def finish_batch(
    conn: sqlite3.Connection,
    batch_id: int,
    *,
    status: str,
    candidate_count: int,
    success_count: int,
    failure_count: int,
    report: dict[str, Any],
) -> None:
    conn.execute(
        """
        UPDATE promotion_batches
        SET status=?, candidate_count=?, success_count=?, failure_count=?, report_json=?
        WHERE id=?
        """,
        (
            status,
            candidate_count,
            success_count,
            failure_count,
            json.dumps(report, ensure_ascii=False),
            batch_id,
        ),
    )


def _view(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["report"] = json.loads(d.pop("report_json") or "{}")
    return d


def list_batches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, scope, run_id, status, candidate_count, success_count,
               failure_count, report_json, created_at
        FROM promotion_batches ORDER BY id DESC
        """
    ).fetchall()
    return [_view(r) for r in rows]


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, scope, run_id, status, candidate_count, success_count,
               failure_count, report_json, created_at
        FROM promotion_batches WHERE id = ?
        """,
        (batch_id,),
    ).fetchone()
    return _view(row) if row else None


def count_batches(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) c FROM promotion_batches").fetchone()["c"])
