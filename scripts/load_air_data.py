#!/usr/bin/env python3
"""
Load Zalopay AIR CSVs into the air-data warehouse (NEW_DATABASE_URL).

Tạo bảng payment_air / search_air rồi nạp dữ liệu bằng COPY (stream, phù hợp file
1.6M dòng). Schema lấy từ agent_core/data_warehouse.py:WAREHOUSE_TABLES.

Usage:
    python scripts/load_air_data.py --dry-run            # chỉ in kế hoạch + đếm dòng
    python scripts/load_air_data.py --recreate           # DROP + tạo lại + nạp
    python scripts/load_air_data.py --truncate           # TRUNCATE + nạp (giữ schema)
    python scripts/load_air_data.py                      # tạo-nếu-chưa-có + nạp (append)

Env (fallback khi không có flag):
    NEW_DATABASE_URL   — đích (Postgres chứa air data)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_core.data_warehouse import WAREHOUSE_TABLES, warehouse_create_ddl  # noqa: E402

CSV_BY_TABLE = {
    "payment_air": "payment_air.csv",
    "search_air": "search_air.csv",
}
CHUNK_SIZE = 1 << 20  # 1 MiB


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Zalopay AIR CSVs into NEW_DATABASE_URL.")
    p.add_argument("--new-url", metavar="DSN", help="Destination DATABASE_URL (overrides env)")
    p.add_argument("--csv-dir", metavar="DIR", default=str(ROOT / "zalopay"), help="Thư mục chứa CSV (default: zalopay/)")
    p.add_argument("--recreate", action="store_true", help="DROP rồi tạo lại bảng trước khi nạp")
    p.add_argument("--truncate", action="store_true", help="TRUNCATE bảng trước khi nạp (giữ schema)")
    p.add_argument("--dry-run", action="store_true", help="Chỉ in kế hoạch + đếm dòng CSV, không ghi")
    return p.parse_args()


def resolve_url(args: argparse.Namespace) -> str:
    if load_dotenv:
        load_dotenv(ROOT / ".env")
    url = args.new_url or os.getenv("NEW_DATABASE_URL") or ""
    if not url and not args.dry_run:
        print("ERROR: NEW_DATABASE_URL is required — set env var or pass --new-url", file=sys.stderr)
        sys.exit(1)
    return url


def count_csv_rows(path: Path) -> int:
    """Đếm dòng dữ liệu (trừ header) mà không nạp cả file vào RAM."""
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            total += chunk.count(b"\n")
    return max(0, total - 1)  # trừ header


def copy_sql_for(table: str) -> str:
    columns = ", ".join(name for name, _ in WAREHOUSE_TABLES[table])
    return f"COPY {table} ({columns}) FROM STDIN (FORMAT csv, HEADER true, NULL '')"


def load_table(conn: psycopg.Connection, table: str, csv_path: Path) -> int:
    with conn.cursor() as cur:
        with open(csv_path, "rb") as handle, cur.copy(copy_sql_for(table)) as copy:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                copy.write(chunk)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - table name từ allowlist nội bộ
        row = cur.fetchone()
    return row[0] if row else 0


def print_dry_run(csv_dir: Path) -> None:
    print("\nDRY-RUN — không ghi vào database.\n")
    w = 14
    print(f"{'Table':<{w}} | {'CSV':<18} | {'Rows (≈)':>12}")
    print("-" * w + "-+-" + "-" * 18 + "-+-" + "-" * 12)
    for table, csv_name in CSV_BY_TABLE.items():
        path = csv_dir / csv_name
        rows = count_csv_rows(path) if path.exists() else -1
        shown = f"{rows:,}" if rows >= 0 else "MISSING"
        print(f"{table:<{w}} | {csv_name:<18} | {shown:>12}")
    print("\nChạy lại với --recreate (DROP+tạo lại) hoặc --truncate để nạp thật.")


def main() -> int:
    args = parse_args()
    csv_dir = Path(args.csv_dir)

    for table, csv_name in CSV_BY_TABLE.items():
        if not (csv_dir / csv_name).exists():
            print(f"WARNING: thiếu CSV {csv_dir / csv_name}", file=sys.stderr)

    if args.dry_run:
        print_dry_run(csv_dir)
        return 0

    url = resolve_url(args)
    print("Kết nối NEW_DATABASE_URL...")
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=15) as conn:
        if args.recreate:
            print("DROP bảng cũ (nếu có)...")
            with conn.cursor() as cur:
                for table in WAREHOUSE_TABLES:
                    cur.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()

        print("Tạo bảng (idempotent)...")
        with conn.cursor() as cur:
            cur.execute(warehouse_create_ddl())
        conn.commit()

        if args.truncate and not args.recreate:
            print("TRUNCATE bảng...")
            with conn.cursor() as cur:
                for table in WAREHOUSE_TABLES:
                    cur.execute(f"TRUNCATE TABLE {table}")
            conn.commit()

        results: list[tuple[str, int]] = []
        for table, csv_name in CSV_BY_TABLE.items():
            csv_path = csv_dir / csv_name
            if not csv_path.exists():
                print(f"  {table}... SKIP (thiếu CSV)")
                results.append((table, -1))
                continue
            print(f"  {table}... đang COPY từ {csv_name}", flush=True)
            count = load_table(conn, table, csv_path)
            print(f"  {table}... {count:,} dòng")
            results.append((table, count))

    print("\nHoàn tất. Tổng kết:")
    w = 14
    print(f"{'Table':<{w}} | {'Rows trong DB':>14}")
    print("-" * w + "-+-" + "-" * 14)
    for table, count in results:
        shown = f"{count:,}" if count >= 0 else "SKIP"
        print(f"{table:<{w}} | {shown:>14}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
