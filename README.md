# Retail Sales Pipeline

A production-style daily batch ETL pipeline built with Python and PostgreSQL.

Pulls store transaction CSVs from an SFTP server, validates and cleans the data,
loads it into a star schema, and surfaces finance reports through SQL views —
all running on a cron schedule.

---

## The problem

RetailCo operates 50 stores. Each store's POS system uploads a daily transactions
CSV to an SFTP server between 11 PM and 1 AM:

```
/incoming/store_001/2026-04-30_transactions.csv
/incoming/store_002/2026-04-30_transactions.csv
```

Finance needs four reports by 8 AM every morning:

1. Total revenue per store
2. Top 10 products by revenue (company-wide)
3. Store rankings (best to worst)
4. Day-over-day revenue comparison

---

## Architecture

```
SFTP Server
    │  store CSVs arrive nightly (11 PM – 1 AM)
    │
    ▼
┌─────────────┐
│  extract.py │  download files for target date → local landing dir
└──────┬──────┘
       │
       ▼
┌──────────────┐
│ validate.py  │  schema check · type coercion · drop bad rows · drop rate guard
└──────┬───────┘
       │
       ▼
┌─────────────┐     ┌─────────────────────┐
│   load.py   │────▶│  raw.sales_staging  │  landing zone (current run only)
└──────┬──────┘     └─────────────────────┘
       │
       ├──────────▶  core.dim_store
       ├──────────▶  core.dim_product
       ├──────────▶  core.dim_date
       └──────────▶  core.fact_sales
                          │
                          ▼
                   reports.daily_revenue_by_store
                   reports.top_products
                   reports.day_over_day
```

**Three-schema design:** `raw` (staging) → `core` (star schema) → `reports` (finance views)

---

## Key engineering decisions

**Idempotency** — Running the pipeline twice for the same date produces identical results.
`ON CONFLICT DO NOTHING` on `fact_sales` means duplicate runs never double-count revenue.

**Transactional loads** — Each file is loaded in a single database transaction.
If the load fails halfway through, the database rolls back to its previous state.
No partial data, no corrupt reports.

**Validation before promotion** — Data lands in `raw.sales_staging` first (no constraints).
Only rows that pass all quality checks are promoted to `core.fact_sales` (strict constraints).
A bad file is skipped; the other stores still load.

**Source traceability** — Every fact row records which file it came from (`source_file` column).
Any suspicious revenue number can be traced back to its source CSV.

**Structured logging** — Every run logs row counts in and out at each stage.
The `core.pipeline_runs` table records metrics for every execution.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Database | PostgreSQL 17 |
| SFTP client | paramiko |
| Data processing | pandas |
| DB driver | psycopg2 |
| Local infrastructure | Docker + docker-compose |
| Scheduling | cron |
| Testing | pytest |

---

## Data model

```
       dim_store              dim_product              dim_date
      ┌──────────┐           ┌──────────┐           ┌──────────┐
      │ store_id │           │product_id│           │ date_id  │
      │ name     │           │ name     │           │ year     │
      │ region   │           │ category │           │ quarter  │
      └────┬─────┘           └────┬─────┘           │ month    │
           │                      │                 │ is_weekend│
           └──────────────────────┼─────────────────┘
                                  │
                          ┌───────▼────────┐
                          │   fact_sales   │
                          │ transaction_id │ ← primary key (idempotency)
                          │ store_id       │
                          │ product_id     │
                          │ quantity       │ CHECK > 0
                          │ unit_price     │ CHECK >= 0
                          │ revenue        │ computed: qty × price
                          │ transaction_ts │
                          │ source_file    │ ← traceability
                          └────────────────┘
```

---

## Validation rules

| Check | Action on failure |
|-------|------------------|
| Missing or renamed column | Raise error, skip entire file |
| Empty file | Raise error, skip entire file |
| Null in required field | Drop row, log count |
| `quantity <= 0` | Drop row, log count |
| `unit_price < 0` | Drop row, log count |
| Duplicate `transaction_id` within file | Keep first, drop rest |
| Drop rate > 5% | Raise error, skip entire file |
| File missing on SFTP | Log warning, continue to next store |
| All stores fail | Exit non-zero (triggers cron alert) |

---

## Getting started

**Prerequisites:** Python 3.12+, Docker Desktop

```bash
# Clone and enter the project
git clone https://github.com/your-username/retail-sales-pipeline.git
cd retail-sales-pipeline

# Install dependencies
pip install -r requirements.txt

# Configure environment (edit .env with your settings)
cp .env.example .env

# Start Postgres + SFTP containers
make up

# Apply database schema
make migrate

# Populate date dimension (2020–2030)
make dates

# Generate and upload 14 days of sample data
make seed
```

---

## Running the pipeline

```bash
# Process yesterday (default — what cron calls)
make run

# Process a specific date
python -m src.main --date 2026-04-20

# Backfill a date range
make backfill FROM=2026-04-20 TO=2026-05-03
```

---

## Sample queries

```sql
-- Revenue by store for a given day
SELECT store_name, total_revenue, transaction_count
FROM reports.daily_revenue_by_store
WHERE sale_date = '2026-05-03'
ORDER BY total_revenue DESC;

-- Top 5 products company-wide today
SELECT product_name, category, units_sold, total_revenue
FROM reports.top_products
WHERE sale_date = '2026-05-03' AND revenue_rank <= 5
ORDER BY revenue_rank;

-- Day-over-day revenue trend
SELECT sale_date, revenue, pct_change
FROM reports.day_over_day
ORDER BY sale_date DESC
LIMIT 7;

-- Pipeline audit log
SELECT run_date, status, rows_extracted, rows_loaded, finished_at - started_at AS duration
FROM core.pipeline_runs
ORDER BY started_at DESC;
```

---

## Make targets

| Command | Description |
|---------|-------------|
| `make up` | Start Docker services |
| `make down` | Stop Docker services |
| `make migrate` | Apply SQL schema |
| `make dates` | Populate dim_date |
| `make seed` | Upload sample data to SFTP |
| `make run` | Run pipeline for yesterday |
| `make backfill FROM=… TO=…` | Backfill a date range |
| `make test` | Run all tests |
| `make psql` | Open Postgres shell |
| `make clean` | Stop containers and delete volumes |

---

## Tests

```bash
make test
```

```
tests/test_extract.py    — unit tests with mocked SFTP (4 tests)
tests/test_validate.py   — unit tests with CSV fixtures (11 tests)
tests/test_load.py       — integration tests against real Postgres (6 tests)
```

---

## Project structure

```
├── src/
│   ├── config.py       — centralised environment config
│   ├── extract.py      — SFTP download logic
│   ├── validate.py     — data quality validation
│   ├── load.py         — database load (staging → dims → facts)
│   └── main.py         — CLI orchestration, logging, audit trail
├── sql/
│   ├── 001_create_schemas.sql
│   ├── 002_create_dim_tables.sql
│   ├── 003_create_fact_tables.sql
│   └── 004_create_reports.sql
├── scripts/
│   ├── apply_sql.py           — idempotent schema migration runner
│   ├── seed_sample_data.py    — generates realistic test data
│   └── populate_dim_date.py   — fills dim_date for 2020–2030
├── tests/
│   ├── test_extract.py
│   ├── test_validate.py
│   └── test_load.py
├── docker-compose.yml
├── Makefile
├── requirements.txt
└── .env.example
```

---

## What comes next

This project deliberately uses a minimal stack (Python + PostgreSQL + cron) to expose its limits:

- No dependency management between steps — if extract fails, load still runs
- No UI for monitoring — debugging means reading log files
- Backfilling many days requires manual date ranges
- Adding a second pipeline duplicates all retry and alert logic

**Project 2** introduces Apache Airflow. Because extract, validate, and load are cleanly
separated functions, the migration is mostly wrapping each one in an Airflow `@task` decorator.
