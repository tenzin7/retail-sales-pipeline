#!/usr/bin/env python3
"""
Populate core.dim_date for 2020-01-01 through 2030-12-31.

Run once after 'make migrate'. Safe to re-run — uses ON CONFLICT DO NOTHING.

Run with: python scripts/populate_dim_date.py
Or:       make dates
"""

import os
from datetime import date, timedelta

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

START = date(2020, 1, 1)
END   = date(2030, 12, 31)


def generate_date_rows() -> list[tuple]:
    rows = []
    d = START
    while d <= END:
        rows.append((
            d,
            d.year,
            (d.month - 1) // 3 + 1,   # quarter: Jan-Mar=1, Apr-Jun=2, ...
            d.month,
            d.strftime("%B"),           # month_name: "January", "February", ...
            d.day,
            d.isoweekday(),             # day_of_week: 1=Monday, 7=Sunday
            d.strftime("%A"),           # day_name: "Monday", "Tuesday", ...
            d.isoweekday() >= 6,        # is_weekend: Saturday=6, Sunday=7
        ))
        d += timedelta(days=1)
    return rows


def main() -> None:
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5433)),
        dbname=os.getenv("POSTGRES_DB", "retail"),
        user=os.getenv("POSTGRES_USER", "retail"),
        password=os.getenv("POSTGRES_PASSWORD", "retail"),
    )

    rows = generate_date_rows()
    print(f"Inserting {len(rows)} dates ({START} → {END}) ...")

    sql = """
        INSERT INTO core.dim_date
            (date_id, year, quarter, month, month_name, day, day_of_week, day_name, is_weekend)
        VALUES %s
        ON CONFLICT (date_id) DO NOTHING
    """
    with conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows)

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
