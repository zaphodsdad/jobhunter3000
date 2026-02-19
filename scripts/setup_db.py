#!/usr/bin/env python3
"""Initialize the JobHunter3000 database. Optionally import spreadsheet data."""

import argparse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db import get_db, ensure_tables, DB_PATH
from services.importer import import_spreadsheet, insert_imported_jobs


def main():
    parser = argparse.ArgumentParser(description="Set up JobHunter3000 database")
    parser.add_argument(
        "--import-spreadsheet",
        type=str,
        default=None,
        help="Path to Excel spreadsheet to import",
    )
    args = parser.parse_args()

    # Ensure data directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    print(f"Database path: {DB_PATH}")
    conn = get_db()
    ensure_tables(conn)
    print("Tables created/verified.")

    if args.import_spreadsheet:
        print(f"\nImporting spreadsheet: {args.import_spreadsheet}")
        jobs = import_spreadsheet(args.import_spreadsheet)
        print(f"Parsed {len(jobs)} jobs from spreadsheet.")

        result = insert_imported_jobs(conn, jobs)
        print(f"Inserted: {result['inserted']}, Skipped (duplicates): {result['skipped']}")

        # Show what we imported
        print("\nImported jobs:")
        for job in jobs:
            status_icon = {
                "applied": "📨",
                "rejected": "❌",
                "interviewing": "🎯",
                "new": "🆕",
            }.get(job["status"], "•")
            print(f"  {status_icon} {job['title']} at {job['company']} [{job['status']}]")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
