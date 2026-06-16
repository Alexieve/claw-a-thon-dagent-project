#!/usr/bin/env python3
"""
Migrate all data from one Postgres database to another.

Usage:
    python scripts/migrate_db.py --old-url <DSN> --new-url <DSN>
    python scripts/migrate_db.py --dry-run   # reads OLD_DATABASE_URL / NEW_DATABASE_URL from .env

Environment variables (fallback when no explicit flags):
    OLD_DATABASE_URL   — source database (fallback: DATABASE_URL from .env)
    NEW_DATABASE_URL   — destination database
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_core.storage import PostgresStorage  # noqa: E402

BATCH_SIZE_DEFAULT = 500

# Tables that have bulk load/save in PostgresStorage, in FK-safe order
# (knowledge_records must precede knowledge_candidates due to FK)
STORAGE_TABLES: list[tuple[str, str, str, str]] = [
    ("knowledge_records",    "load_knowledge_base",    "save_knowledge_base",    "knowledge"),
    ("knowledge_candidates", "load_candidates",         "save_candidates",        "candidates"),
    ("teaching_sessions",    "load_teaching_sessions",  "save_teaching_sessions", "sessions"),
    ("chat_sessions",        "load_chat_sessions",      "save_chat_sessions",     "sessions"),
    ("data_dictionary",      "load_data_dictionary",    "save_data_dictionary",   "records"),
    ("question_examples",    "load_question_examples",  "save_question_examples", "examples"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migrate all Postgres data from an old database to a new one."
    )
    p.add_argument("--old-url", metavar="DSN", help="Source DATABASE_URL (overrides env)")
    p.add_argument("--new-url", metavar="DSN", help="Destination DATABASE_URL (overrides env)")
    p.add_argument("--dry-run", action="store_true", help="Count rows in old DB, no writes")
    p.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE_DEFAULT,
        metavar="N",
        help=f"Rows per INSERT batch for raw_events/document_chunks (default {BATCH_SIZE_DEFAULT})",
    )
    return p.parse_args()


def resolve_urls(args: argparse.Namespace) -> tuple[str, str]:
    if load_dotenv:
        load_dotenv(ROOT / ".env")
    old_url = args.old_url or os.getenv("OLD_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
    new_url = args.new_url or os.getenv("NEW_DATABASE_URL") or ""
    if not old_url:
        print("ERROR: OLD_DATABASE_URL (or DATABASE_URL) is required — set env var or pass --old-url", file=sys.stderr)
        sys.exit(1)
    if not new_url and not args.dry_run:
        print("ERROR: NEW_DATABASE_URL is required — set env var or pass --new-url", file=sys.stderr)
        sys.exit(1)
    return old_url, new_url


def count_all_tables(database_url: str) -> dict[str, int]:
    tables = [
        "knowledge_records", "knowledge_candidates", "teaching_sessions",
        "chat_sessions", "data_dictionary", "question_examples",
        "raw_events", "document_chunks",
    ]
    counts: dict[str, int] = {}
    with psycopg.connect(database_url, prepare_threshold=None, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                row = cur.fetchone()
                counts[table] = row[0] if row else 0
    return counts


def migrate_via_storage(
    old: PostgresStorage, new: PostgresStorage
) -> dict[str, int]:
    results: dict[str, int] = {}
    for table, load_method, save_method, container_key in STORAGE_TABLES:
        data = getattr(old, load_method)()
        count = len(data.get(container_key, {}))
        getattr(new, save_method)(data)
        results[table] = count
    return results


def _copy_jsonl_table(
    old_url: str,
    new_url: str,
    *,
    table: str,
    select_sql: str,
    insert_sql: str,
    row_to_params,
    batch_size: int,
) -> int:
    total = 0
    with (
        psycopg.connect(old_url, prepare_threshold=None, connect_timeout=10) as old_conn,
        psycopg.connect(new_url, prepare_threshold=None, connect_timeout=10) as new_conn,
    ):
        with (
            old_conn.cursor(row_factory=dict_row) as src_cur,
            new_conn.cursor() as dst_cur,
        ):
            src_cur.execute(select_sql)
            while True:
                rows = src_cur.fetchmany(batch_size)
                if not rows:
                    break
                batch = [row_to_params(r) for r in rows]
                dst_cur.executemany(insert_sql, batch)
                new_conn.commit()
                total += len(rows)
    return total


def _raw_event_params(row: dict[str, Any]) -> tuple:
    created_at = row["created_at"]
    return (
        row["id"],
        row["source_type"],
        row.get("stakeholder", ""),
        row.get("team", ""),
        row.get("document_id", ""),
        row.get("status", "parsed"),
        row.get("raw_text", ""),
        created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        json.dumps(row["payload"], ensure_ascii=False),
    )


def _document_chunk_params(row: dict[str, Any]) -> tuple:
    created_at = row["created_at"]
    return (
        row["id"],
        row["document_id"],
        row.get("chunk_index", 0),
        row.get("title", ""),
        created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        json.dumps(row["payload"], ensure_ascii=False),
    )


def migrate_raw_events(old_url: str, new_url: str, batch_size: int) -> int:
    return _copy_jsonl_table(
        old_url, new_url,
        table="raw_events",
        select_sql=(
            "SELECT id, source_type, stakeholder, team, document_id, status, raw_text, created_at, payload "
            "FROM raw_events ORDER BY created_at"
        ),
        insert_sql="""
            INSERT INTO raw_events
              (id, source_type, stakeholder, team, document_id, status, raw_text, created_at, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            ON CONFLICT (id) DO NOTHING
        """,
        row_to_params=_raw_event_params,
        batch_size=batch_size,
    )


def migrate_document_chunks(old_url: str, new_url: str, batch_size: int) -> int:
    return _copy_jsonl_table(
        old_url, new_url,
        table="document_chunks",
        select_sql=(
            "SELECT id, document_id, chunk_index, title, created_at, payload "
            "FROM document_chunks ORDER BY document_id, chunk_index"
        ),
        insert_sql="""
            INSERT INTO document_chunks
              (id, document_id, chunk_index, title, created_at, payload)
            VALUES (%s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            ON CONFLICT (id) DO NOTHING
        """,
        row_to_params=_document_chunk_params,
        batch_size=batch_size,
    )


def print_dry_run(old_counts: dict[str, int]) -> None:
    print("\nDRY-RUN — reading old DB, no writes to new DB.\n")
    w = 26
    print(f"{'Table':<{w}} | {'Old count':>9}")
    print("-" * w + "-+-" + "-" * 9)
    total = 0
    for table, count in old_counts.items():
        print(f"{table:<{w}} | {count:>9}")
        total += count
    print(f"\nTotal: {total} rows across {len(old_counts)} tables.")
    print("No data was written to the new database.")


def print_summary(results: list[dict[str, Any]]) -> None:
    w = 26
    header = f"{'Table':<{w}} | {'Old':>9} | {'Migrated':>9} | {'New':>9} | Status"
    sep = "-" * w + "-+-" + "-" * 9 + "-+-" + "-" * 9 + "-+-" + "-" * 9 + "-+-------"
    print(f"\nMigration complete. Verifying new DB...\n")
    print(header)
    print(sep)
    for r in results:
        print(f"{r['table']:<{w}} | {r['old']:>9} | {r['migrated']:>9} | {r['new']:>9} | {r['status']}")
    errors = [r for r in results if r["status"].startswith("ERROR")]
    warns = [r for r in results if r["status"] == "WARN"]
    print()
    if errors:
        print(f"FAILED: {len(errors)} table(s) had errors.")
    elif warns:
        print(f"Done with warnings: {len(warns)} table(s) have count mismatch (new DB may already have data).")
    else:
        print("All 8 tables migrated successfully.")


def main() -> int:
    args = parse_args()
    old_url, new_url = resolve_urls(args)

    print("Connecting to old DB and counting rows...")
    try:
        old_counts = count_all_tables(old_url)
    except Exception as exc:
        print(f"ERROR: cannot connect to old DB: {exc}", file=sys.stderr)
        raise

    if args.dry_run:
        print_dry_run(old_counts)
        return 0

    print("Bootstrapping new DB schema (idempotent)...")
    try:
        new_storage = PostgresStorage(new_url)
        new_storage.bootstrap()
    except Exception as exc:
        print(f"ERROR: cannot bootstrap new DB: {exc}", file=sys.stderr)
        raise

    old_storage = PostgresStorage(old_url)

    results: list[dict[str, Any]] = []
    try:
        print("Migrating 6 tables via PostgresStorage...")
        storage_migrated: dict[str, int] = {}
        for table, load_method, save_method, container_key in STORAGE_TABLES:
            print(f"  {table}...", end=" ", flush=True)
            try:
                data = getattr(old_storage, load_method)()
                count = len(data.get(container_key, {}))
                getattr(new_storage, save_method)(data)
                storage_migrated[table] = count
                print(f"{count} rows")
            except Exception as exc:
                storage_migrated[table] = -1
                print(f"ERROR: {exc}")

        print("Migrating raw_events...")
        raw_migrated = -1
        try:
            raw_migrated = migrate_raw_events(old_url, new_url, args.batch_size)
            print(f"  raw_events... {raw_migrated} rows")
        except Exception as exc:
            print(f"  raw_events... ERROR: {exc}")

        print("Migrating document_chunks...")
        chunks_migrated = -1
        try:
            chunks_migrated = migrate_document_chunks(old_url, new_url, args.batch_size)
            print(f"  document_chunks... {chunks_migrated} rows")
        except Exception as exc:
            print(f"  document_chunks... ERROR: {exc}")

        print("\nVerifying new DB counts...")
        new_counts = count_all_tables(new_url)

        for table, _, _, _ in STORAGE_TABLES:
            old_c = old_counts[table]
            mig_c = storage_migrated.get(table, -1)
            new_c = new_counts[table]
            if mig_c == -1:
                status = "ERROR: migration failed"
            elif new_c == old_c:
                status = "OK"
            elif new_c > old_c:
                status = "WARN"
            else:
                status = f"WARN ({new_c - old_c:+d})"
            results.append({"table": table, "old": old_c, "migrated": mig_c, "new": new_c, "status": status})

        for table, migrated_c in [("raw_events", raw_migrated), ("document_chunks", chunks_migrated)]:
            old_c = old_counts[table]
            new_c = new_counts[table]
            if migrated_c == -1:
                status = "ERROR: migration failed"
            elif new_c == old_c:
                status = "OK"
            elif new_c > old_c:
                status = "WARN"
            else:
                status = f"WARN ({new_c - old_c:+d})"
            results.append({"table": table, "old": old_c, "migrated": migrated_c, "new": new_c, "status": status})

    finally:
        if old_storage._pool is not None:
            old_storage._pool.close()
        if new_storage._pool is not None:
            new_storage._pool.close()

    print_summary(results)
    return 1 if any(r["status"].startswith("ERROR") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
