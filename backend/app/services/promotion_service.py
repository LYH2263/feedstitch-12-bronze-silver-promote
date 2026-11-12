"""Promotion orchestration: reconcile then atomically move bronze → canonical."""

from __future__ import annotations

from typing import Any

from app.db import connect
from app.modules.bronze_silver_promote import reconcile_groups
from app.repositories import bronze as bronze_repo
from app.repositories import canonical as canon_repo
from app.repositories import promotions as promotions_repo
from app.repositories import runs as runs_repo


def _group_for_run(conn, run_id: int) -> tuple[Any, list[dict], list[dict]] | None:
    run = runs_repo.get_run(conn, run_id)
    if run is None:
        return None
    recorded = bronze_repo.list_by_run(conn, run_id)
    pending = [r for r in recorded if r["status"] == "pending"]
    return run, recorded, pending


def _build_report(
    conn,
    *,
    scope: str,
    checks: list[dict[str, Any]],
    candidate_count: int,
    success_count: int,
    failure_count: int,
    candidate_rows: list[dict[str, Any]],
    message: str,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "run_ids": sorted({c["run_id"] for c in checks if c.get("run_id") is not None}),
        "candidate_count": candidate_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "ingest_expected_count": sum(
            int(c["expected_count"] or 0) for c in checks
        ),
        "already_promoted_count": sum(
            int(c.get("already_promoted_count") or 0) for c in checks
        ),
        "bronze_pending_count_after": bronze_repo.count(conn, status="pending"),
        "canonical_count_after": canon_repo.count_items(conn),
        "candidates": [
            {
                "bronze_row_id": r["id"],
                "run_id": r["run_id"],
                "business_key": r["business_key"],
            }
            for r in candidate_rows
        ],
        "checks": checks,
        "message": message,
    }


def promote(run_id: int | None = None) -> dict[str, Any]:
    """Run the promotion gate for one ingest run or for all pending rows.

    All-or-nothing: if any run in scope fails reconciliation, no canonical row
    is written for that request. Every targeted bronze row stays in the
    pending zone and carries a failure reason.
    """
    conn = connect()
    try:
        scope = "run" if run_id is not None else "pending"

        if run_id is not None:
            group = _group_for_run(conn, run_id)
            if group is None:
                raise ValueError("run not found")
            groups = [group]
        else:
            group_run_ids = sorted(
                {r["run_id"] for r in bronze_repo.list_pending(conn)}
            )
            groups = []
            for rid in group_run_ids:
                group = _group_for_run(conn, rid)
                if group is None:
                    groups.append((None, [], []))
                else:
                    groups.append(group)

        checks = reconcile_groups(groups)
        candidate_rows = [
            r for _, _, pending in groups for r in pending
        ]
        candidate_ids = [r["id"] for r in candidate_rows]
        candidate_count = len(candidate_rows)
        all_passed = all(c["passed"] for c in checks)

        batch_id = promotions_repo.create_batch(
            conn,
            scope=scope,
            run_id=run_id,
            candidate_count=candidate_count,
        )

        if not all_passed:
            reason_by_run: dict[int | None, str] = {}
            for c in checks:
                if c["passed"]:
                    reason = "batch aborted: another run failed reconciliation"
                else:
                    reason = "; ".join(c["issues"]) or "reconciliation failed"
                reason_by_run[c.get("run_id")] = reason

            for row in candidate_rows:
                bronze_repo.mark_failed(
                    conn,
                    row_ids=[row["id"]],
                    promotion_id=batch_id,
                    reason=reason_by_run.get(row["run_id"], "reconciliation failed"),
                )

            failure_summary = [
                {"run_id": c.get("run_id"), "issues": c["issues"]}
                for c in checks
                if not c["passed"]
            ]
            report = _build_report(
                conn,
                scope=scope,
                checks=checks,
                candidate_count=candidate_count,
                success_count=0,
                failure_count=candidate_count,
                candidate_rows=candidate_rows,
                message="reconciliation failed; rows kept in bronze/pending zone",
            )
            report["failure_summary"] = failure_summary
            promotions_repo.finish_batch(
                conn,
                batch_id,
                status="failed",
                candidate_count=candidate_count,
                success_count=0,
                failure_count=candidate_count,
                report=report,
            )
            conn.commit()
            return promotions_repo.get_batch(conn, batch_id) or {}

        # Gate passed: apply all candidates in one transaction. Apply per key
        # in ascending revision order so the newest state wins even if pending
        # rows for a key arrived out of order.
        success_count = 0
        try:
            apply_order = sorted(
                candidate_rows,
                key=lambda r: (
                    r["business_key"],
                    int(r["source_revision"]),
                    r["event_ts"],
                    r["id"],
                ),
            )
            for row in apply_order:
                canon_repo.upsert_item(conn, row, row["source_id"])
                success_count += 1
            bronze_repo.mark_promoted(
                conn,
                row_ids=candidate_ids,
                promotion_id=batch_id,
            )
            report = _build_report(
                conn,
                scope=scope,
                checks=checks,
                candidate_count=candidate_count,
                success_count=success_count,
                failure_count=0,
                candidate_rows=candidate_rows,
                message=(
                    "promoted to canonical" if candidate_count
                    else "no pending bronze rows in scope"
                ),
            )
            promotions_repo.finish_batch(
                conn,
                batch_id,
                status="passed",
                candidate_count=candidate_count,
                success_count=success_count,
                failure_count=0,
                report=report,
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            error = f"promotion write failed: {exc}"
            batch_id = promotions_repo.create_batch(
                conn,
                scope=scope,
                run_id=run_id,
                candidate_count=candidate_count,
            )
            bronze_repo.mark_failed(
                conn,
                row_ids=candidate_ids,
                promotion_id=batch_id,
                reason=error,
            )
            checks_with_error = [{**c, "passed": False, "issues": c["issues"] + [error]}
                                 for c in checks]
            report = _build_report(
                conn,
                scope=scope,
                checks=checks_with_error,
                candidate_count=candidate_count,
                success_count=0,
                failure_count=candidate_count,
                candidate_rows=candidate_rows,
                message=error,
            )
            report["failure_summary"] = [
                {"run_id": c.get("run_id"), "issues": c["issues"]}
                for c in checks_with_error
            ]
            promotions_repo.finish_batch(
                conn,
                batch_id,
                status="failed",
                candidate_count=candidate_count,
                success_count=0,
                failure_count=candidate_count,
                report=report,
            )
            conn.commit()

        return promotions_repo.get_batch(conn, batch_id) or {}
    finally:
        conn.close()


def list_promotions() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return promotions_repo.list_batches(conn)
    finally:
        conn.close()


def get_promotion(batch_id: int) -> dict[str, Any] | None:
    conn = connect()
    try:
        return promotions_repo.get_batch(conn, batch_id)
    finally:
        conn.close()
