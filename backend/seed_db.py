#!/usr/bin/env python3
"""One-shot schema + seed for the WebGIS asset-tracking database.

Run this against a freshly-created (empty) Render free Postgres to provision the
entire database in a single command — handy because Render's free Postgres
expires every 30 days, so re-creating it is a recurring chore.

Connection (first match wins):
  1. --dsn "postgresql://user:pass@host/db"   Render -> Database -> "External
     Connection String" (use the EXTERNAL one when running from your laptop).
  2. DATABASE_URL environment variable.
  3. DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASS  (same vars app.py reads).

Files are applied in DEPENDENCY order, which intentionally differs from the
order listed in render.yaml:

    01_schema.sql        postgis extension + assets table + GIST index
    03_history.sql       asset_history + trigger (so each asset INSERT
                         auto-logs an "origin" history row)
    05_interactions.sql  interactions table + view  <-- MUST exist before 04
    04_clustered_seed.sql 150 assets, ~30 history steps each, 25 past
                         interactions

Why 05 before 04: 04's interaction backfill is skipped unless the interactions
table already exists (see sql/04_clustered_seed.sql). Running 04 before 05
leaves the side panel empty until the live simulator fills it.

Usage (PowerShell):
    python backend/seed_db.py --dsn "postgresql://USER:PASS@HOST/DB"
    python backend/seed_db.py --dsn "postgresql://..." --reset   # wipe first
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2

# Apply order matters — see module docstring.
FILES = ["01_schema.sql", "03_history.sql", "05_interactions.sql", "04_clustered_seed.sql"]

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

# CASCADE truncates asset_history + interactions too (both FK to assets).
RESET_SQL = "TRUNCATE assets RESTART IDENTITY CASCADE;"


def connect(dsn):
    """Open a connection from --dsn, then DATABASE_URL, then the DB_* vars."""
    if dsn:
        return psycopg2.connect(dsn)
    url = os.getenv("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.getenv("DB_NAME", "asset_tracking"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", ""),
    )


def main():
    ap = argparse.ArgumentParser(description="Provision the asset-tracking DB in one shot.")
    ap.add_argument("--dsn", help="Postgres connection string (Render External Connection String).")
    ap.add_argument("--reset", action="store_true", help="TRUNCATE existing data before seeding (non-empty DB).")
    args = ap.parse_args()

    missing = [f for f in FILES if not (SQL_DIR / f).exists()]
    if missing:
        sys.exit(f"Missing SQL files in {SQL_DIR}: {', '.join(missing)}")

    try:
        conn = connect(args.dsn)
    except psycopg2.Error as exc:
        sys.exit(f"Could not connect: {exc}")

    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            if args.reset:
                print("Resetting existing tables ...", end=" ", flush=True)
                try:
                    cur.execute(RESET_SQL)
                    conn.commit()
                    print("ok")
                except psycopg2.Error:
                    conn.rollback()  # tables don't exist yet on a fresh DB
                    print("nothing to reset (fresh database)")

            for fname in FILES:
                sql = (SQL_DIR / fname).read_text(encoding="utf-8")
                print(f"Applying {fname} ...", end=" ", flush=True)
                cur.execute(sql)
                conn.commit()
                print("ok")

            counts = {}
            for tbl in ("assets", "asset_history", "interactions"):
                cur.execute(f"SELECT count(*) FROM {tbl}")
                counts[tbl] = cur.fetchone()[0]
    finally:
        conn.close()

    print("\nDone. Row counts:")
    for tbl, n in counts.items():
        print(f"  {tbl:<14} {n}")
    if counts["interactions"] == 0:
        print("\nWARNING: 0 interactions — the side panel will start empty.")
        print("This happens if 04 ran before 05. Re-run this script (it uses the right order).")


if __name__ == "__main__":
    main()
