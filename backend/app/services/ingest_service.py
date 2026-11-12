from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.merge_rules import decide_merge, eligible_for_incremental
from app.engines.parse_feed import parse_fixture
from app.repositories import bronze as bronze_repo
from app.repositories import canonical as canon_repo
from app.repositories import promotions as promotions_repo
from app.repositories import runs as runs_repo
from app.repositories import sources as sources_repo


def preview_source(source_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        source = sources_repo.get_source(conn, source_id)
        if not source:
            raise ValueError("source not found")
        path = FIXTURES_DIR / source["fixture_path"]
        items = parse_fixture(path, source["format"])
        return {
            "source": source,
            "count": len(items),
            "items": items[:50],
        }
    finally:
        conn.close()


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "business_key": row["business_key"],
        "title": row["title"],
        "price": row["price"],
        "category": row["category"],
        "event_ts": row["event_ts"],
        "source_revision": row["source_revision"],
        "payload": row["payload"],
    }


def _effective_view(conn, business_key: str) -> dict[str, Any] | None:
    """Newest state across canonical and pending bronze for a business key."""
    canonical = canon_repo.get_by_key(conn, business_key)
    pending = bronze_repo.latest_for_key(conn, business_key)
    if canonical is None:
        return _row_view(pending) if pending else None
    if pending is None:
        return _row_view(canonical)
    # Prefer the higher revision; event_ts/id break ties. Pending wins ties so
    # an in-flight candidate is not silently superseded by stale canonical.
    canonical_rank = (int(canonical["source_revision"]), canonical["event_ts"])
    pending_rank = (int(pending["source_revision"]), pending["event_ts"])
    return _row_view(pending) if pending_rank >= canonical_rank else _row_view(canonical)


def run_ingest(source_id: int, mode: str = "incremental") -> dict[str, Any]:
    if mode not in ("incremental", "full"):
        raise ValueError("mode must be incremental or full")

    conn = connect()
    try:
        source = sources_repo.get_source(conn, source_id)
        if not source:
            raise ValueError("source not found")
        if not source["enabled"]:
            raise ValueError("source disabled")

        if mode == "full":
            sources_repo.set_watermark(conn, source_id, None)
            source["watermark_ts"] = None

        run_id = runs_repo.create_run(conn, source_id, mode)
        path = FIXTURES_DIR / source["fixture_path"]

        try:
            items = parse_fixture(path, source["format"])
        except Exception as exc:  # noqa: BLE001
            runs_repo.finish_run(
                conn,
                run_id,
                status="failed",
                parsed=0,
                upserted=0,
                conflicts=0,
                skipped=0,
                report={"error": str(exc)},
            )
            conn.commit()
            raise

        parsed = 0
        upserted = 0
        conflicts = 0
        skipped = 0
        max_event_ts: str | None = source.get("watermark_ts")
        dispositions: list[str] = []
        accepted_keys: list[str] = []

        for item in items:
            parsed += 1
            if mode == "incremental" and not eligible_for_incremental(
                item["event_ts"],
                source.get("watermark_ts"),
                int(source.get("lookback_seconds") or 0),
            ):
                runs_repo.insert_staging(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition="skipped_watermark",
                )
                skipped += 1
                dispositions.append("skipped_watermark")
                continue

            # Effective master = newest state across canonical (promoted) and
            # pending bronze. This keeps merge/conflict decisions correct
            # without letting unpromoted rows pollute canonical.
            existing_view = _effective_view(conn, item["business_key"])

            decision = decide_merge(existing_view, item)
            if decision in ("insert", "upsert"):
                # Bronze/pending zone: canonical is only written by promotion.
                bronze_repo.insert_row(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition=decision,
                )
                runs_repo.insert_staging(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition=decision,
                )
                upserted += 1
                accepted_keys.append(item["business_key"])
                dispositions.append(decision)
                if max_event_ts is None or item["event_ts"] > max_event_ts:
                    max_event_ts = item["event_ts"]
            elif decision == "conflict":
                runs_repo.insert_conflict(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    business_key=item["business_key"],
                    existing_payload=existing_view["payload"] if existing_view else {},
                    incoming_payload=item["payload"],
                    reason="non_key_field_mismatch",
                )
                runs_repo.insert_staging(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition="quarantine",
                )
                conflicts += 1
                dispositions.append("quarantine")
                if max_event_ts is None or item["event_ts"] > max_event_ts:
                    max_event_ts = item["event_ts"]
            else:
                runs_repo.insert_staging(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition="skip_stale",
                )
                skipped += 1
                dispositions.append("skip_stale")
                if max_event_ts is None or item["event_ts"] > max_event_ts:
                    max_event_ts = item["event_ts"]

        if max_event_ts:
            sources_repo.set_watermark(conn, source_id, max_event_ts)

        canonical_count = canon_repo.count_items(conn)
        report = {
            "source_id": source_id,
            "mode": mode,
            "parsed_count": parsed,
            # upserted_count keeps its historical column meaning: rows accepted
            # into the pipeline. They now land in bronze/pending, not canonical.
            "upserted_count": upserted,
            "accepted_count": upserted,
            "conflict_count": conflicts,
            "skipped_count": skipped,
            "bronze_candidate_count": upserted,
            "bronze_business_keys": accepted_keys,
            "bronze_pending_count": bronze_repo.count(conn, status="pending"),
            "canonical_count": canonical_count,
            "watermark_ts": max_event_ts,
            "dispositions": dispositions,
        }
        runs_repo.finish_run(
            conn,
            run_id,
            status="ok",
            parsed=parsed,
            upserted=upserted,
            conflicts=conflicts,
            skipped=skipped,
            report=report,
        )
        conn.commit()
        run = runs_repo.get_run(conn, run_id)
        return run or report
    finally:
        conn.close()


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        sources = sources_repo.list_sources(conn)
        return {
            "source_count": len(sources),
            "enabled_sources": sum(1 for s in sources if s["enabled"]),
            "canonical_count": canon_repo.count_items(conn),
            "bronze_pending_count": bronze_repo.count(conn, status="pending"),
            "bronze_promoted_count": bronze_repo.count(conn, status="promoted"),
            "conflict_count": conn.execute("SELECT COUNT(*) c FROM conflicts").fetchone()["c"],
            "run_count": conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"],
            "staging_count": conn.execute("SELECT COUNT(*) c FROM staging_rows").fetchone()["c"],
            "promotion_count": promotions_repo.count_batches(conn),
        }
    finally:
        conn.close()
