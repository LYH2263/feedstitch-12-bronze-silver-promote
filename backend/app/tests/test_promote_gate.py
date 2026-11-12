from app.modules.bronze_silver_promote import reconcile_run


def _run(report, status="ok", run_id=1):
    return {"id": run_id, "status": status, "report": report}


def _row(row_id, key, run_id=1, disposition="insert", status="pending"):
    return {
        "id": row_id,
        "run_id": run_id,
        "business_key": key,
        "disposition": disposition,
        "status": status,
    }


def test_gate_passes_when_count_and_keys_match_report():
    report = {
        "bronze_candidate_count": 3,
        "bronze_business_keys": ["SKU-1", "SKU-2", "SKU-3"],
    }
    rows = [_row(1, "SKU-1"), _row(2, "SKU-2"), _row(3, "SKU-3")]
    result = reconcile_run(_run(report), rows, rows)
    assert result["passed"] is True
    assert result["issues"] == []
    assert result["pending_count"] == 3
    assert result["expected_count"] == 3


def test_gate_fails_on_count_mismatch():
    report = {
        "bronze_candidate_count": 3,
        "bronze_business_keys": ["SKU-1", "SKU-2", "SKU-3"],
    }
    rows = [_row(1, "SKU-1"), _row(2, "SKU-2")]
    result = reconcile_run(_run(report), rows, rows)
    assert result["passed"] is False
    assert any("row count" in i for i in result["issues"])


def test_gate_fails_on_key_set_mismatch():
    report = {
        "bronze_candidate_count": 2,
        "bronze_business_keys": ["SKU-1", "SKU-2"],
    }
    rows = [_row(1, "SKU-1"), _row(2, "SKU-9")]
    result = reconcile_run(_run(report), rows, rows)
    assert result["passed"] is False
    assert any("business-key set mismatch" in i for i in result["issues"])


def test_gate_accepts_already_promoted_rows_so_retry_is_noop():
    report = {
        "bronze_candidate_count": 2,
        "bronze_business_keys": ["SKU-1", "SKU-2"],
    }
    recorded = [
        _row(1, "SKU-1", status="promoted"),
        _row(2, "SKU-2", status="promoted"),
    ]
    result = reconcile_run(_run(report), recorded, [])
    assert result["passed"] is True
    assert result["pending_count"] == 0
    assert result["already_promoted_count"] == 2


def test_gate_rejects_non_promotable_disposition_and_bad_status():
    report = {
        "bronze_candidate_count": 1,
        "bronze_business_keys": ["SKU-1"],
    }
    rows = [_row(1, "SKU-1", disposition="quarantine")]
    result = reconcile_run(_run(report, status="failed"), rows, rows)
    assert result["passed"] is False
    assert any("non-promotable" in i for i in result["issues"])
    assert any("status" in i for i in result["issues"])


def test_gate_fails_when_run_report_missing():
    result = reconcile_run(None, [_row(1, "SKU-1")], [_row(1, "SKU-1")])
    assert result["passed"] is False
    assert any("report not found" in i for i in result["issues"])


def test_gate_uses_multiset_for_duplicate_business_keys():
    report = {
        "bronze_candidate_count": 2,
        "bronze_business_keys": ["SKU-1", "SKU-1"],
    }
    rows = [_row(1, "SKU-1"), _row(2, "SKU-1")]
    result = reconcile_run(_run(report), rows, rows)
    assert result["passed"] is True
