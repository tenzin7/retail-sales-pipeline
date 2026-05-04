"""
Pipeline entry point — orchestrates extract → validate → load.

Single date:
    python -m src.main                              # yesterday (default)
    python -m src.main --date 2026-04-20            # specific date

Backfill a range:
    python -m src.main --backfill-from 2026-04-01 --backfill-to 2026-04-30
    python -m src.main --backfill-from 2026-04-01   # from date → yesterday
"""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

from src import config
from src.extract import download_files_for_date
from src.load import get_connection, run_load
from src.validate import ValidationError, validate_file

logger = logging.getLogger(__name__)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retail sales ETL pipeline")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Single date to process (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--backfill-from",
        type=date.fromisoformat,
        dest="backfill_from",
        help="Start of backfill range (YYYY-MM-DD, inclusive).",
    )
    parser.add_argument(
        "--backfill-to",
        type=date.fromisoformat,
        dest="backfill_to",
        help="End of backfill range (YYYY-MM-DD, inclusive). Defaults to yesterday.",
    )
    return parser.parse_args()


def get_dates(args: argparse.Namespace) -> list[date]:
    """Resolve CLI args to an ordered list of dates to process."""
    yesterday = date.today() - timedelta(days=1)

    if args.backfill_from:
        start = args.backfill_from
        end   = args.backfill_to or yesterday
        if start > end:
            print(f"ERROR: --backfill-from {start} is after --backfill-to {end}")
            sys.exit(1)
        n = (end - start).days + 1
        return [start + timedelta(days=i) for i in range(n)]

    return [args.date or yesterday]


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging(label: str) -> None:
    """
    label is used for the log filename — either a date (daily run)
    or "backfill_YYYYMMDD" (backfill run).
    """
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = config.LOG_DIR / f"pipeline_{label}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ── Audit log ─────────────────────────────────────────────────────────────────

def log_run_start(conn, run_date: date, started_at: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO core.pipeline_runs (run_date, started_at, status)
            VALUES (%s, %s, 'running')
            RETURNING run_id
            """,
            (run_date, started_at),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def log_run_finish(
    conn,
    run_id: int,
    status: str,
    rows_extracted: int,
    rows_loaded: int,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE core.pipeline_runs
            SET finished_at    = CURRENT_TIMESTAMP,
                status         = %s,
                rows_extracted = %s,
                rows_loaded    = %s,
                error_message  = %s
            WHERE run_id = %s
            """,
            (status, rows_extracted, rows_loaded, error_message, run_id),
        )
    conn.commit()


# ── Per-date processing ───────────────────────────────────────────────────────

def process_date(run_date: date, conn) -> bool:
    """
    Run the full extract → validate → load cycle for one date.
    Returns True on success, False on failure.
    Failures are logged but do not raise — so a backfill continues past bad dates.
    """
    logger.info("--- Processing %s ---", run_date)

    run_id        = log_run_start(conn, run_date, datetime.now())
    rows_extracted = 0
    rows_loaded    = 0

    try:
        local_files = download_files_for_date(run_date)

        if not local_files:
            raise RuntimeError(f"No files downloaded for {run_date}")

        failed_files = []

        for path in local_files:
            try:
                df = validate_file(path)
                rows_extracted += len(df)
                rows_loaded    += run_load(df, conn)
                logger.info("Loaded %s (%d rows)", path.name, len(df))
            except ValidationError as e:
                logger.error("Skipping %s — %s", path.name, e)
                failed_files.append(path.name)

        if failed_files:
            logger.warning("Skipped %d file(s): %s", len(failed_files), failed_files)

        if len(failed_files) == len(local_files):
            raise RuntimeError("All files failed validation — nothing loaded")

        if rows_loaded == 0:
            logger.info("No new rows inserted — idempotent re-run")

        log_run_finish(conn, run_id, "success", rows_extracted, rows_loaded)
        return True

    except Exception as e:
        logger.exception("Failed for %s", run_date)
        log_run_finish(conn, run_id, "failed", rows_extracted, rows_loaded, str(e))
        return False


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args      = parse_args()
    dates     = get_dates(args)
    is_backfill = len(dates) > 1

    log_label = (
        f"backfill_{date.today().strftime('%Y%m%d')}"
        if is_backfill
        else dates[0].strftime("%Y%m%d")
    )
    setup_logging(log_label)

    if is_backfill:
        logger.info(
            "=== Backfill starting: %s → %s (%d dates) ===",
            dates[0], dates[-1], len(dates),
        )
    else:
        logger.info("=== Pipeline starting for %s ===", dates[0])

    conn      = get_connection()
    succeeded = sum(process_date(d, conn) for d in dates)
    conn.close()

    if is_backfill:
        logger.info(
            "=== Backfill complete: %d/%d dates succeeded ===",
            succeeded, len(dates),
        )

    if succeeded == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
