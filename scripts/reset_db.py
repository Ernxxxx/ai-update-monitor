#!/usr/bin/env python3
"""Database reset utility for testing purposes.

Usage:
    python scripts/reset_db.py [--delete | --reset]

Options:
    --delete  Delete the database file completely
    --reset   Drop and recreate tables (default)
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db import delete_db, reset_db, init_db

# Default database path (same as config.py default)
DEFAULT_DB_PATH = os.getenv("DB_PATH", "state.db")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset or delete the state.db database for testing."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--delete",
        action="store_true",
        help="Delete the database file completely",
    )
    group.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate tables (default)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    args = parser.parse_args()
    db_path = args.db_path or DEFAULT_DB_PATH

    # Default to reset if neither specified
    action = "delete" if args.delete else "reset"

    if not args.yes:
        response = input(
            f"Are you sure you want to {action} the database at {db_path}? [y/N]: "
        )
        if response.lower() not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)

    if action == "delete":
        if delete_db(db_path):
            print(f"Deleted database: {db_path}")
        else:
            print(f"Database file not found: {db_path}")
    else:
        reset_db(db_path)
        print(f"Reset database: {db_path}")


if __name__ == "__main__":
    main()
