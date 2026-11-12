from fastapi import APIRouter, Query

from app.db import connect
from app.repositories import bronze as bronze_repo

router = APIRouter(tags=["bronze"])


@router.get("/bronze")
def list_bronze(
    status: str | None = Query(default="pending"),
    run_id: int | None = Query(default=None),
):
    """Bronze / pending-promotion zone, plus summary counts.

    ``status=pending`` (default) shows the rows waiting for the gate;
    pass ``status=promoted`` (or omit status entirely via ``status=``) to inspect
    the audit trail. The summary always exposes both counts so it can be
    reconciled with the promotion report.
    """
    conn = connect()
    try:
        requested_status = None if status in (None, "", "all") else status
        rows = bronze_repo.list_rows(conn, status=requested_status, run_id=run_id)
        return {
            "rows": rows,
            "status_filter": requested_status,
            "pending_count": bronze_repo.count(conn, status="pending"),
            "promoted_count": bronze_repo.count(conn, status="promoted"),
            "total_count": bronze_repo.count(conn),
            "by_run": bronze_repo.counts_by_run(conn),
        }
    finally:
        conn.close()
