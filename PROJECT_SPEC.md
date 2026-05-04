# Retail Sales Pipeline — Project Specification

## 1. Business Context

**RetailCo** operates 50 stores. Each store's POS system uploads a daily transactions CSV to an SFTP server between 11 PM and 1 AM:

```
/incoming/store_001/2026-04-30_transactions.csv
/incoming/store_002/2026-04-30_transactions.csv
...
```

Each CSV contains line-item-level transactions:

```csv
transaction_id,store_id,product_id,product_name,category,quantity,unit_price,transaction_ts
T100234,001,P5521,"Organic Milk 1L",Dairy,2,3.49,2026-04-30 14:23:11
T100235,001,P3310,"Whole Wheat Bread",Bakery,1,4.99,2026-04-30 14:23:45
```

**Finance requires by 8 AM daily:**
1. Total revenue per store
2. Top 10 products by revenue (company-wide)
3. Store rankings (best to worst)
4. Day-over-day comparison

## 2. Design Decisions (Up Front)

Answered before writing code:

- **Source of truth:** the CSVs — immutable once uploaded
- **Grain:** one row per line item per transaction
- **Failure modes to handle:** missing uploads, corrupted files, late arrivals, duplicate uploads, silent schema changes
- **Definition of done:** reports correct in Postgres by 8 AM daily, with alerts on any failure

## 3. Technology Stack

- **Python 3.13** — pandas, psycopg2-binary, paramiko, python-dotenv, pytest (Python 3.14 works too; 3.13 recommended for fewer library compatibility surprises)
- **PostgreSQL 17** — relational store for dims, facts, and report views (Postgres 18 works too; 17 is more battle-tested with more community resources)
- **Docker / docker-compose** — local Postgres and mock SFTP server
- **Cron** — scheduling
- **Git** — version control

Nothing else. Resist scope creep.

## 4. Project Structure

```
retail-pipeline/
├── README.md
├── CLAUDE.md
├── PROJECT_SPEC.md
├── requirements.txt
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Makefile
├── sql/
│   ├── 001_create_schemas.sql
│   ├── 002_create_dim_tables.sql
│   ├── 003_create_fact_tables.sql
│   └── 004_create_reports.sql
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── extract.py
│   ├── validate.py
│   ├── load.py
│   └── main.py
├── scripts/
│   ├── apply_sql.py
│   └── seed_sample_data.py
├── tests/
│   ├── __init__.py
│   ├── test_validate.py
│   └── test_load.py
└── logs/
```

## 5. Database Design

### Schemas

| Schema    | Purpose                                           |
|-----------|---------------------------------------------------|
| `raw`     | Untouched staging data — audit trail, never modified after load |
| `core`    | Cleaned dimensions and facts — the model           |
| `reports` | Views consumed by finance / BI                     |

### Star Schema

```
       dim_store              dim_product              dim_date
      ┌──────────┐           ┌──────────┐           ┌──────────┐
      │ store_id │           │product_id│           │ date_id  │
      │ name     │           │ name     │           │ year     │
      │ region   │           │ category │           │ month    │
      └────┬─────┘           └────┬─────┘           │ day      │
           │                      │                 │day_of_wk │
           │                      │                 └────┬─────┘
           │                      │                      │
           └──────────────────────┼──────────────────────┘
                                  │
                          ┌───────▼────────┐
                          │   fact_sales   │
                          │ transaction_id │
                          │ store_id (FK)  │
                          │ product_id(FK) │
                          │ date_id (FK)   │
                          │ quantity       │
                          │ unit_price     │
                          │ revenue        │
                          │ transaction_ts │
                          │ loaded_at      │
                          └────────────────┘
```

### `sql/001_create_schemas.sql`

```sql
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS reports;
```

### `sql/002_create_dim_tables.sql`

```sql
CREATE TABLE IF NOT EXISTS core.dim_store (
    store_id      VARCHAR(10) PRIMARY KEY,
    store_name    VARCHAR(100) NOT NULL,
    region        VARCHAR(50),
    opened_date   DATE,
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS core.dim_product (
    product_id    VARCHAR(10) PRIMARY KEY,
    product_name  VARCHAR(200) NOT NULL,
    category      VARCHAR(50),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS core.dim_date (
    date_id       DATE PRIMARY KEY,
    year          INTEGER NOT NULL,
    quarter       INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    month_name    VARCHAR(20) NOT NULL,
    day           INTEGER NOT NULL,
    day_of_week   INTEGER NOT NULL,
    day_name      VARCHAR(20) NOT NULL,
    is_weekend    BOOLEAN NOT NULL
);
```

### `sql/003_create_fact_tables.sql`

```sql
CREATE TABLE IF NOT EXISTS raw.sales_staging (
    transaction_id    VARCHAR(20),
    store_id          VARCHAR(10),
    product_id        VARCHAR(10),
    product_name      VARCHAR(200),
    category          VARCHAR(50),
    quantity          INTEGER,
    unit_price        NUMERIC(10,2),
    transaction_ts    TIMESTAMP,
    source_file       VARCHAR(255),
    loaded_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS core.fact_sales (
    transaction_id    VARCHAR(20) PRIMARY KEY,
    store_id          VARCHAR(10) NOT NULL REFERENCES core.dim_store(store_id),
    product_id        VARCHAR(10) NOT NULL REFERENCES core.dim_product(product_id),
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    unit_price        NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
    revenue           NUMERIC(12,2) NOT NULL,
    transaction_ts    TIMESTAMP NOT NULL,
    source_file       VARCHAR(255),
    loaded_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fact_sales_ts ON core.fact_sales(transaction_ts);
CREATE INDEX IF NOT EXISTS idx_fact_sales_store ON core.fact_sales(store_id);

CREATE TABLE IF NOT EXISTS core.pipeline_runs (
    run_id        SERIAL PRIMARY KEY,
    run_date      DATE NOT NULL,
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    status        VARCHAR(20) NOT NULL,
    rows_extracted INTEGER,
    rows_loaded   INTEGER,
    error_message TEXT
);
```

### `sql/004_create_reports.sql`

```sql
CREATE OR REPLACE VIEW reports.daily_revenue_by_store AS
SELECT
    DATE(f.transaction_ts) AS sale_date,
    s.store_id,
    s.store_name,
    s.region,
    COUNT(DISTINCT f.transaction_id) AS transaction_count,
    SUM(f.quantity) AS units_sold,
    SUM(f.revenue) AS total_revenue
FROM core.fact_sales f
JOIN core.dim_store s ON f.store_id = s.store_id
GROUP BY 1, 2, 3, 4;

CREATE OR REPLACE VIEW reports.top_products AS
SELECT
    DATE(f.transaction_ts) AS sale_date,
    p.product_id,
    p.product_name,
    p.category,
    SUM(f.quantity) AS units_sold,
    SUM(f.revenue) AS total_revenue,
    RANK() OVER (
      PARTITION BY DATE(f.transaction_ts)
      ORDER BY SUM(f.revenue) DESC
    ) AS revenue_rank
FROM core.fact_sales f
JOIN core.dim_product p ON f.product_id = p.product_id
GROUP BY 1, 2, 3, 4;

CREATE OR REPLACE VIEW reports.day_over_day AS
WITH daily AS (
    SELECT DATE(transaction_ts) AS sale_date,
           SUM(revenue) AS revenue
    FROM core.fact_sales
    GROUP BY 1
)
SELECT
    sale_date,
    revenue,
    LAG(revenue) OVER (ORDER BY sale_date) AS prior_day_revenue,
    revenue - LAG(revenue) OVER (ORDER BY sale_date) AS day_over_day_change,
    ROUND(
      100.0 * (revenue - LAG(revenue) OVER (ORDER BY sale_date))
      / NULLIF(LAG(revenue) OVER (ORDER BY sale_date), 0), 2
    ) AS pct_change
FROM daily;
```

### Why these design choices

| Decision | Reasoning |
|----------|-----------|
| `transaction_id` as PK on `fact_sales` | Free idempotency — duplicate runs fail on conflict |
| `CHECK` constraints on quantity/price | DB refuses bad data; bugs can't silently corrupt reports |
| `source_file` column | Trace any row back to the file it came from |
| `loaded_at` separate from `transaction_ts` | Distinguishes when something happened vs when we processed it |
| Three-schema split (raw/core/reports) | Audit trail, clean model, polished output — debuggable layers |
| Staging table in `raw` | Validate before promoting — failures don't pollute core |
| `pipeline_runs` audit table | Every run logs metrics — operational visibility |

## 6. Pipeline Flow

```
SFTP server
    │
    ▼
[Extract] download_files_for_date(date) ──► local landing dir
    │
    ▼
[Validate] validate_file(path) ──► clean DataFrame OR raises ValidationError
    │
    ▼
[Load] run_load(df) ──► transactional:
                          1. truncate raw.sales_staging
                          2. INSERT df into raw.sales_staging
                          3. UPSERT new stores into core.dim_store
                          4. UPSERT new products into core.dim_product
                          5. INSERT new rows into core.fact_sales (ON CONFLICT DO NOTHING)
    │
    ▼
[Reports] views in reports.* always reflect latest data
```

## 7. Module Responsibilities

### `src/config.py`
Loads environment variables. Single source for all config. No logic.

### `src/extract.py`
Connects to SFTP, downloads CSVs for a target date, returns local file paths. Missing files are logged as warnings — they do not crash the pipeline.

### `src/validate.py`
Reads a CSV with pandas. Validates schema (raises on mismatch). Coerces types with `errors="coerce"`. Drops rows with nulls in required fields, non-positive quantities, negative prices, in-file duplicates. Logs counts at every drop. Raises `ValidationError` if drop rate exceeds 5%.

### `src/load.py`
Single transaction:
1. Truncate `raw.sales_staging`
2. Bulk insert validated DataFrame into staging
3. Upsert dimensions (`ON CONFLICT DO NOTHING` for store, `DO UPDATE` for product)
4. Insert into `core.fact_sales` with `ON CONFLICT (transaction_id) DO NOTHING`

### `src/main.py`
CLI entry point. Argparse with `--date` (defaults to yesterday). Orchestrates extract → validate → load. Sets up logging to `logs/pipeline_YYYYMMDD.log`. Exits non-zero on any failure so cron's mail-on-failure works.

## 8. Validation Rules

| Check | Action on failure |
|-------|------------------|
| Schema mismatch (missing/extra columns) | Raise `ValidationError`, abort file |
| Null in required field | Drop row, log count |
| `quantity <= 0` | Drop row, log count |
| `unit_price < 0` | Drop row, log count |
| Duplicate `transaction_id` within file | Keep first, drop rest, log count |
| Drop rate > 5% | Raise `ValidationError`, abort file |
| File missing on SFTP | Log warning, continue with other files |
| All files fail | Exit pipeline with error |

## 9. Idempotency Strategy

- **Extract:** re-downloading the same file overwrites the local copy — safe
- **Validate:** pure function of input file — deterministic
- **Load staging:** `TRUNCATE` then `INSERT` — always fresh
- **Load dims:** `ON CONFLICT DO NOTHING` (store) or `DO UPDATE` (product)
- **Load facts:** `ON CONFLICT (transaction_id) DO NOTHING`

Net result: running `python -m src.main --date 2026-04-30` ten times produces identical state.

## 10. Scheduling

```cron
0 2 * * * cd /opt/retail-pipeline && /opt/retail-pipeline/venv/bin/python -m src.main >> logs/cron.log 2>&1 || mail -s "Pipeline FAILED" oncall@retailco.com < logs/cron.log
```

- 2 AM daily — buffer after 11 PM–1 AM upload window
- Reports due 8 AM — 6 hours of slack for retries
- Non-zero exit triggers email alert

## 11. Build Phases

Work in order. Commit after each phase.

### Phase 1 — Local environment
- `docker-compose.yml` with Postgres 15 and `atmoz/sftp`
- `Makefile` with `make up`, `make down`, `make psql`, `make seed`, `make test`, `make run`
- `scripts/seed_sample_data.py` — generates realistic CSVs for 10 stores × 14 days, uploads to local SFTP
- `requirements.txt`, `.env.example`, `.gitignore`

### Phase 2 — Database setup
- All SQL files from Section 5
- `scripts/apply_sql.py` — applies SQL files in numerical order, idempotent
- Verify with `\dt core.*` in psql

### Phase 3 — Extract
- `src/config.py`, `src/extract.py`
- Test that mocks paramiko, asserts missing files are logged but don't crash

### Phase 4 — Validate
- `src/validate.py`, `tests/test_validate.py`
- Tests for: valid file, missing column, negative quantity, null required field, duplicate transaction_id, drop-rate threshold
- All tests pass under `pytest`

### Phase 5 — Load
- `src/load.py`
- Integration test against dockerized Postgres: load → assert row count → load again → assert no duplicates

### Phase 6 — Orchestrate
- `src/main.py` with argparse and logging config
- End-to-end run against seeded data
- Deliberately break things: corrupt a CSV, drop a column, duplicate a file — observe correct behavior
- Populate `core.dim_date` for 2020–2030

### Phase 7 — Schedule and polish
- Cron entry
- `pipeline_runs` audit table populated by `src/main.py`
- `--backfill-from` and `--backfill-to` CLI flags
- README with setup and run instructions

## 12. Definition of Done

- [ ] `make up && make seed && make run` works end-to-end
- [ ] `pytest` passes
- [ ] Pipeline is idempotent (verified by running twice, comparing row counts)
- [ ] All three report views return correct data
- [ ] Backfill works for any historical date in seeded range
- [ ] Logs are clear and actionable
- [ ] `pipeline_runs` table populated for every run
- [ ] README explains how to set up and run from scratch
- [ ] Git history has clean phase-by-phase commits

## 13. What Comes Next (Not in This Project)

This project intentionally stops at cron + raw SQL. You will feel the limits:

- Cron has no dependency management — extract fails, transform still runs
- No visibility — debugging means SSH and tail
- Adding a second pipeline duplicates retry/alert logic
- Backfilling many days = bash for-loops that stop on first failure
- Transformations as raw SQL files have no tests, docs, or lineage

**Project 2 introduces Apache Airflow.** Because extract/validate/load are cleanly separated, the migration is mostly wrapping each function in a `@task` decorator.

**Do not introduce Airflow, dbt, or cloud services in this project.** The point is to feel the limits of the basic stack first.
