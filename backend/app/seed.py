from app.db import connect


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS sources(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            format TEXT NOT NULL,
            fixture_path TEXT NOT NULL,
            watermark_ts TEXT,
            lookback_seconds INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS runs(
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            parsed_count INTEGER NOT NULL,
            upserted_count INTEGER NOT NULL,
            conflict_count INTEGER NOT NULL,
            skipped_count INTEGER NOT NULL,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS staging_rows(
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            business_key TEXT NOT NULL,
            event_ts TEXT NOT NULL,
            source_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            disposition TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS canonical_items(
            id INTEGER PRIMARY KEY,
            business_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            event_ts TEXT NOT NULL,
            source_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conflicts(
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            business_key TEXT NOT NULL,
            existing_payload TEXT NOT NULL,
            incoming_payload TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        -- Bronze / 待晋升区：ingest 先落这里，晋升闸通过后才写 canonical。
        CREATE TABLE IF NOT EXISTS bronze_rows(
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            business_key TEXT NOT NULL,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            event_ts TEXT NOT NULL,
            source_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            disposition TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            promotion_id INTEGER,
            failure_reason TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            promoted_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_bronze_status ON bronze_rows(status);
        CREATE INDEX IF NOT EXISTS idx_bronze_run ON bronze_rows(run_id);
        CREATE INDEX IF NOT EXISTS idx_bronze_key ON bronze_rows(business_key);
        -- 晋升批次：每次晋升尝试一条，成功/失败报告持久化。
        CREATE TABLE IF NOT EXISTS promotion_batches(
            id INTEGER PRIMARY KEY,
            scope TEXT NOT NULL,
            run_id INTEGER,
            status TEXT NOT NULL,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            report_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    if conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"] == 0:
        conn.executemany(
            """
            INSERT INTO sources(name, format, fixture_path, watermark_ts, lookback_seconds, enabled, note)
            VALUES (?,?,?,?,?,?,?)
            """,
            [
                (
                    "Alpha Catalog",
                    "json",
                    "alpha_catalog.json",
                    None,
                    0,
                    1,
                    "clean：三件独立货号，首跑应全部 upsert",
                ),
                (
                    "Beta Offers",
                    "jsonl",
                    "beta_offers.jsonl",
                    None,
                    0,
                    1,
                    "dirty：SKU-1001 与 Alpha 同键异价→冲突；另含独立货号",
                ),
                (
                    "Gamma Shelf",
                    "xml",
                    "gamma_shelf.xml",
                    None,
                    0,
                    1,
                    "xml 源：两件独立货号",
                ),
            ],
        )
        conn.execute("INSERT INTO settings(key, value) VALUES ('project_label', 'Feedstitch')")
        conn.execute("INSERT INTO settings(key, value) VALUES ('default_mode', 'incremental')")
        conn.commit()
    conn.close()
