#!/usr/bin/env python3
"""
Generate synthetic transaction CSVs and upload them to the local SFTP server.

Run with: python scripts/seed_sample_data.py
Requires: make up (Docker services must be running)
"""

import io
import os
import random
from datetime import date, datetime, timedelta

import pandas as pd
import paramiko
from dotenv import load_dotenv

load_dotenv()

SFTP_HOST = os.getenv("SFTP_HOST", "localhost")
SFTP_PORT = int(os.getenv("SFTP_PORT", 2222))
SFTP_USER = os.getenv("SFTP_USER", "retail")
SFTP_PASSWORD = os.getenv("SFTP_PASSWORD", "retail")
SFTP_BASE_PATH = os.getenv("SFTP_BASE_PATH", "/incoming")

STORES = ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010"]

# Fixed product catalog — 30 items across 5 categories
# (product_id, product_name, category, unit_price)
PRODUCTS = [
    ("P001", "Organic Milk 1L",          "Dairy",      3.49),
    ("P002", "Greek Yogurt 500g",         "Dairy",      2.99),
    ("P003", "Cheddar Cheese 200g",       "Dairy",      5.49),
    ("P004", "Butter 250g",               "Dairy",      4.29),
    ("P005", "Heavy Cream 500ml",         "Dairy",      3.79),
    ("P006", "Sour Cream 300ml",          "Dairy",      2.49),
    ("P007", "Whole Wheat Bread",         "Bakery",     4.99),
    ("P008", "Sourdough Loaf",            "Bakery",     6.49),
    ("P009", "Croissant 4-pack",          "Bakery",     5.99),
    ("P010", "Blueberry Muffins 6-pack",  "Bakery",     7.49),
    ("P011", "Bagels 6-pack",             "Bakery",     4.79),
    ("P012", "Cinnamon Rolls 4-pack",     "Bakery",     6.99),
    ("P013", "Bananas 1kg",               "Produce",    1.99),
    ("P014", "Fuji Apples 1.5kg",         "Produce",    4.49),
    ("P015", "Baby Spinach 200g",         "Produce",    3.29),
    ("P016", "Roma Tomatoes 500g",        "Produce",    2.79),
    ("P017", "Avocado 3-pack",            "Produce",    4.99),
    ("P018", "Broccoli Crown",            "Produce",    2.49),
    ("P019", "Strawberries 500g",         "Produce",    4.99),
    ("P020", "Chicken Breast 1kg",        "Meat",      11.99),
    ("P021", "Ground Beef 500g",          "Meat",       8.49),
    ("P022", "Salmon Fillet 400g",        "Meat",      13.99),
    ("P023", "Pork Chops 600g",           "Meat",       9.49),
    ("P024", "Italian Sausage 400g",      "Meat",       6.99),
    ("P025", "Orange Juice 1L",           "Beverages",  4.49),
    ("P026", "Sparkling Water 6-pack",    "Beverages",  5.99),
    ("P027", "Cold Brew Coffee 500ml",    "Beverages",  6.49),
    ("P028", "Green Tea 20-pack",         "Beverages",  4.99),
    ("P029", "Coconut Water 1L",          "Beverages",  3.99),
    ("P030", "Kombucha 480ml",            "Beverages",  4.79),
]

# Transaction volume peaks at lunch (12-13) and after work (17-18)
_HOUR_WEIGHTS = {8: 2, 9: 3, 10: 4, 11: 6, 12: 8, 13: 7, 14: 5,
                 15: 4, 16: 5, 17: 8, 18: 9, 19: 7, 20: 4, 21: 2}
_HOURS = list(_HOUR_WEIGHTS.keys())
_WEIGHTS = list(_HOUR_WEIGHTS.values())


def generate_transactions(store_id: str, sale_date: date, rng: random.Random) -> pd.DataFrame:
    """Return a DataFrame of line-item transactions for one store on one date."""
    n_items = rng.randint(80, 150)
    rows = []
    date_compact = sale_date.strftime("%Y%m%d")

    for i in range(n_items):
        pid, pname, category, unit_price = rng.choice(PRODUCTS)
        quantity = rng.choices([1, 2, 3, 4, 5], weights=[50, 30, 12, 5, 3])[0]

        hour = rng.choices(_HOURS, weights=_WEIGHTS)[0]
        ts = datetime(sale_date.year, sale_date.month, sale_date.day,
                      hour, rng.randint(0, 59), rng.randint(0, 59))

        rows.append({
            "transaction_id": f"T{store_id}{date_compact}{i + 1:04d}",
            "store_id":        store_id,
            "product_id":      pid,
            "product_name":    pname,
            "category":        category,
            "quantity":        quantity,
            "unit_price":      unit_price,
            "transaction_ts":  ts.strftime("%Y-%m-%d %H:%M:%S"),
        })

    return pd.DataFrame(rows)


def ensure_remote_dir(sftp: paramiko.SFTPClient, path: str) -> None:
    """Create remote directory if it does not already exist."""
    try:
        sftp.stat(path)
    except IOError:
        sftp.mkdir(path)


def main() -> None:
    # Fixed seed makes every run produce identical files — idempotency at the data level
    rng = random.Random(42)

    today = date.today()
    # 14 days ending yesterday (today's files arrive overnight and aren't ready yet)
    dates = [today - timedelta(days=d) for d in range(14, 0, -1)]

    print(f"Connecting to SFTP {SFTP_HOST}:{SFTP_PORT} ...")
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(transport)

    # AutoAddPolicy is fine for local dev — we own this server
    # (paramiko.Transport.connect doesn't check host keys; that's RSAKey territory)

    total_files = 0
    total_rows = 0

    ensure_remote_dir(sftp, SFTP_BASE_PATH)

    for store_id in STORES:
        store_dir = f"{SFTP_BASE_PATH}/store_{store_id}"
        ensure_remote_dir(sftp, store_dir)

        for sale_date in dates:
            df = generate_transactions(store_id, sale_date, rng)

            remote_path = f"{store_dir}/{sale_date.strftime('%Y-%m-%d')}_transactions.csv"

            # Write CSV into memory, then upload — no temp files on disk
            buf = io.StringIO()
            df.to_csv(buf, index=False)

            with sftp.open(remote_path, "w") as f:
                f.write(buf.getvalue())

            total_files += 1
            total_rows += len(df)

        print(f"  store_{store_id}: {len(dates)} files")

    sftp.close()
    transport.close()

    print(f"\nDone. {total_files} files uploaded, {total_rows:,} rows total.")
    print(f"Date range: {dates[0]} → {dates[-1]}")


if __name__ == "__main__":
    main()
