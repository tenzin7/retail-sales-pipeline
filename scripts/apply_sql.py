#!/usr/bin/env python3
"""
Apply all SQL files in sql/ to Postgres in numerical order.

Idempotent: every statement uses CREATE IF NOT EXISTS or CREATE OR REPLACE,
so running this twice produces the same result as running it once.

Run with: python scripts/apply_sql.py
Or:       make migrate
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = int(os.getenv("POSTGRES_PORT", 5433))
DB_NAME = os.getenv("POSTGRES_DB", "retail")
DB_USER = os.getenv("POSTGRES_USER", "retail")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "retail")

SQL_DIR = Path(__file__).parent.parent / "sql"


def get_sql_files() -> list[Path]:
    """Return .sql files sorted by filename (001_, 002_, ...)."""
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        print(f"No .sql files found in {SQL_DIR}")
        sys.exit(1)
    return files


def apply(conn: psycopg2.extensions.connection, path: Path) -> None:
    """Execute one SQL file inside a transaction. Rolls back on any error."""
    sql = path.read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"  ✓ {path.name}")


def main() -> None:
    print(f"Connecting to {DB_HOST}:{DB_PORT}/{DB_NAME} ...")
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASS
        )
    except psycopg2.OperationalError as e:
        print(f"ERROR: Could not connect to Postgres.\n{e}")
        print("Is 'make up' running?")
        sys.exit(1)

    sql_files = get_sql_files()
    print(f"Applying {len(sql_files)} SQL files from {SQL_DIR}:\n")

    try:
        for path in sql_files:
            apply(conn, path)
    except Exception as e:
        conn.rollback()
        print(f"\nERROR in {path.name}:\n{e}")
        sys.exit(1)
    finally:
        conn.close()

    print("\nDone. Database schema is ready.")


if __name__ == "__main__":
    main()
