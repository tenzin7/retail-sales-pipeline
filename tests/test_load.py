"""
Integration tests for src/load.py

These tests run against the real Dockerized Postgres — not mocks.
Requires: make up (Docker must be running)

If Postgres is not reachable the tests are skipped, not failed,
so 'make test' still passes when Docker is down.
"""

import pandas as pd
import psycopg2
import pytest

from src.load import get_connection, run_load


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def conn():
    """Open one connection for the whole module; skip all tests if DB is down."""
    try:
        c = get_connection()
        yield c
        c.close()
    except psycopg2.OperationalError:
        pytest.skip("Postgres not reachable — run 'make up' first")


def _wipe(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM core.fact_sales")
        cur.execute("DELETE FROM core.dim_product")
        cur.execute("DELETE FROM core.dim_store")
        cur.execute("TRUNCATE raw.sales_staging")
    conn.commit()


@pytest.fixture(autouse=True)
def clean_tables(conn):
    """Wipe tables before and after each test — guards against leftover pipeline data."""
    _wipe(conn)
    yield
    _wipe(conn)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_df(transaction_ids: list[str] | None = None) -> pd.DataFrame:
    if transaction_ids is None:
        transaction_ids = ["TTEST0001", "TTEST0002", "TTEST0003"]

    rows = [
        {
            "transaction_id": txn_id,
            "store_id":       "001",
            "product_id":     "P001",
            "product_name":   "Organic Milk 1L",
            "category":       "Dairy",
            "quantity":       2,
            "unit_price":     3.49,
            "transaction_ts": pd.Timestamp("2026-04-20 12:34:55"),
            "source_file":    "test.csv",
        }
        for txn_id in transaction_ids
    ]
    return pd.DataFrame(rows)


def count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_load_inserts_rows_into_staging_and_facts(conn):
    df = make_df()
    run_load(df, conn)

    assert count(conn, "raw.sales_staging") == 3
    assert count(conn, "core.fact_sales")   == 3


def test_load_populates_dim_store(conn):
    run_load(make_df(), conn)
    assert count(conn, "core.dim_store") == 1


def test_load_populates_dim_product(conn):
    run_load(make_df(), conn)
    assert count(conn, "core.dim_product") == 1


def test_load_is_idempotent(conn):
    """Running load twice with the same data must not create duplicate rows."""
    df = make_df()
    run_load(df, conn)
    run_load(df, conn)   # second run — same transaction_ids

    # Staging is truncated and refilled on each run
    assert count(conn, "raw.sales_staging") == 3
    # Facts must not have duplicates
    assert count(conn, "core.fact_sales") == 3


def test_revenue_is_calculated_correctly(conn):
    """Revenue = quantity × unit_price, computed by load.py not trusted from source."""
    df = make_df(["TTEST_REV"])
    df.loc[0, "quantity"]   = 3
    df.loc[0, "unit_price"] = 5.00

    run_load(df, conn)

    with conn.cursor() as cur:
        cur.execute("SELECT revenue FROM core.fact_sales WHERE transaction_id = 'TTEST_REV'")
        revenue = cur.fetchone()[0]

    assert float(revenue) == 15.00


def test_staging_is_truncated_on_each_run(conn):
    """Staging must only contain the most recent run's data, not accumulate."""
    run_load(make_df(["TTEST_A1", "TTEST_A2"]), conn)
    assert count(conn, "raw.sales_staging") == 2

    run_load(make_df(["TTEST_B1"]), conn)
    assert count(conn, "raw.sales_staging") == 1   # old rows gone
