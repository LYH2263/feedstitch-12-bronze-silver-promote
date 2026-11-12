# 01-feedstitch（信汇）

Feedstitch — 多源目录/价目 Feed 归并落库：解析 → 业务键去重/冲突隔离 → 按源水位线增量或全量落库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5100 |
| API | http://localhost:10100 |

## 主链

配置源与夹具 → 触发 Run → 解析 / 去重 / 冲突隔离 → **Bronze 待晋升区** → 对账闸 → **Canonical（Silver）**

- 摄取报告（Run report）记录 `bronze_candidate_count` 与 `bronze_business_keys`；尚未晋升的行只存在于 Bronze。
- 晋升台（`POST /api/promotions`）对选定批次或全部待晋升行做对账：条数与业务键多重集必须与摄取报告一致，才整批写 Canonical 并标记 `promoted`。
- 对账失败时整批保留在 Bronze，`failure_reason` 逐行落库；晋升批次报告持久化在 `promotion_batches`，刷新后仍可查看。
- 两区列表：待晋升区（`/bronze`，`GET /api/bronze`）与正式主数据（`/canonical`，`GET /api/canonical`）。

## 种子说明

- **Alpha Catalog（clean）**：JSON，三件干净货号，增量可落库。
- **Beta Offers（dirty）**：JSONL，含与 Alpha 同键但价格不同的冲突行，以及迟到低 revision 行（底座增量会因水位线跳过）。
- **Gamma Shelf（xml）**：简易 XML，两件独立货号。

打开“运行台”选源跑一次增量，再打开“待晋升区”确认候选，最后在“晋升台”对账晋升，看两区计数与摄取 / 晋升报告是否一致。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现）

`lookback_backfill` / `schema_drift_guard` / `dead_letter_replay` / `webhook_push_source` /
`source_authority_rank` / `tombstone_retire` / `scd2_history` / `watermark_commit_gate` /
`field_map_transform` / `lineage_provenance` /
`fixture_dir_harvest` / `category_metric_mart` / `pii_mask_export` /
`rpa_form_queue`
