"""Read-only executor cho air data warehouse (NEW_DATABASE_URL).

Tách biệt khỏi PostgresStorage (metadata DB cũ): module này chỉ CHẠY các câu
SELECT do LLM sinh ra lên database chứa dữ liệu air (payment_air / search_air).
Mọi truy vấn đều chạy trong transaction READ ONLY + statement_timeout + rollback,
qua một validator chỉ cho phép một câu SELECT/WITH duy nhất.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
from typing import Any

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency for JSON-only local mode
    psycopg = None

try:
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover - optional; falls back to per-call connections
    ConnectionPool = None


# Single source of truth cho schema warehouse: tên cột (LOWERCASE, không quote) + kiểu Postgres,
# theo đúng thứ tự cột trong CSV. Dùng cho: (1) loader sinh DDL + COPY column list,
# (2) prompt sinh SQL biết schema thật. Tên cột để lowercase nên SQL không-quote của LLM
# (vd reqDate, userID) tự fold về lowercase và khớp.
WAREHOUSE_TABLES: dict[str, list[tuple[str, str]]] = {
    "payment_air": [
        ("transid", "BIGINT"),
        ("appid", "INTEGER"),
        ("amount", "BIGINT"),
        ("apptransid", "TEXT"),
        ("appuser", "TEXT"),
        ("reqdate", "TIMESTAMP"),
        ("userid", "BIGINT"),
        ("round_type", "TEXT"),
        ("origin", "TEXT"),
        ("dest", "TEXT"),
        ("route", "TEXT"),
        ("flight_type", "TEXT"),
        ("in_out_bound", "TEXT"),
        ("flight_date", "DATE"),
        ("booking_window", "INTEGER"),
        ("booking_window_group", "TEXT"),
        ("etl_date", "TIMESTAMP"),
    ],
    "search_air": [
        ("user_id", "BIGINT"),
        ("activity_time", "TIMESTAMP"),
        ("product_line", "TEXT"),
        ("departure", "TEXT"),
        ("dest", "TEXT"),
        ("route", "TEXT"),
        ("departure_date", "DATE"),
        ("trip_type", "TEXT"),
        ("search_date", "DATE"),
        ("search_day_in_week", "TEXT"),
        ("departure_day_in_week", "TEXT"),
        ("day_diff", "INTEGER"),
        ("user_search_group", "TEXT"),
        ("etl_date", "TIMESTAMP"),
    ],
}

# Khoảng thời gian dữ liệu có sẵn (theo playbook_sql_air_views.md) — hint cho LLM chọn
# date literal rơi vào vùng có data, tránh trả về 0 dòng do filter sai khoảng.
DATA_COVERAGE = {
    "search_air": "search_date khoảng 2025-11-01 .. 2026-02-28",
    "payment_air": "reqDate khoảng 2024-12-01 .. 2025-01-31 và 2025-12-01 .. 2026-02-28",
    "join_overlap": "Khi JOIN search_air và payment_air, vùng chồng lấn an toàn là 2025-12-01 .. 2026-02-28",
}

DEFAULT_MAX_ROWS = 1000
DEFAULT_TIMEOUT_MS = 15000

# Câu SQL hợp lệ phải bắt đầu bằng SELECT hoặc WITH (sau khi strip comment).
_LEADING_OK = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
# Keyword ghi / DDL bị cấm ở bất kỳ đâu (kể cả trong CTE writable của WITH).
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"merge|call|do|vacuum|reindex|refresh|lock|copy|into|attach|"
    r"set|reset|begin|commit|rollback|savepoint|listen|notify)\b",
    re.IGNORECASE,
)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")


def strip_sql_comments(sql: str) -> str:
    """Bỏ comment để check keyword/cấu trúc; không dùng cho việc execute."""
    no_block = _BLOCK_COMMENT.sub(" ", sql)
    return _LINE_COMMENT.sub(" ", no_block)


def validate_readonly_select(sql: str) -> tuple[bool, str]:
    """Chỉ cho phép MỘT câu SELECT/WITH thuần đọc. Trả (ok, reason)."""
    raw = (sql or "").strip()
    if not raw:
        return False, "SQL rỗng."
    stripped = strip_sql_comments(raw).strip()
    if not stripped:
        return False, "SQL chỉ chứa comment, không có câu lệnh."
    if not _LEADING_OK.match(stripped):
        return False, "Chỉ cho phép câu lệnh bắt đầu bằng SELECT hoặc WITH."
    # Bỏ tối đa các dấu ; ở cuối, nếu còn ; ở giữa -> nhiều statement.
    body = stripped.rstrip().rstrip(";").rstrip()
    if ";" in body:
        return False, "Chỉ cho phép một câu lệnh duy nhất (phát hiện nhiều statement)."
    forbidden = _FORBIDDEN.search(body)
    if forbidden:
        return False, f"Phát hiện từ khoá không cho phép trong câu đọc: {forbidden.group(0).upper()}."
    return True, ""


def warehouse_create_ddl() -> str:
    """Sinh DDL idempotent từ WAREHOUSE_TABLES (single source of truth)."""
    parts: list[str] = []
    for table, columns in WAREHOUSE_TABLES.items():
        cols = ",\n  ".join(f"{name} {col_type}" for name, col_type in columns)
        parts.append(f"create table if not exists {table} (\n  {cols}\n);")
    return "\n\n".join(parts) + "\n"


def warehouse_schema_summary() -> str:
    """Mô tả schema gọn cho prompt: table(col type, ...)."""
    lines: list[str] = []
    for table, columns in WAREHOUSE_TABLES.items():
        cols = ", ".join(f"{name} {col_type}" for name, col_type in columns)
        lines.append(f"{table}({cols})")
    return "\n".join(lines)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).decode("utf-8", "replace")
        except Exception:  # pragma: no cover - defensive
            return str(value)
    return str(value)


class DataWarehouse:
    """Pool kết nối tới air-data DB và chạy SELECT thuần đọc, có giới hạn."""

    def __init__(
        self,
        database_url: str,
        *,
        max_rows: int | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required for NEW_DATABASE_URL queries")
        self.database_url = database_url
        self.max_rows = max_rows or int(os.getenv("DATA_QUERY_MAX_ROWS") or DEFAULT_MAX_ROWS)
        self.timeout_ms = timeout_ms or int(os.getenv("DATA_QUERY_TIMEOUT_MS") or DEFAULT_TIMEOUT_MS)
        # Pool giống PostgresStorage: prepare_threshold=None bắt buộc cho Supabase pooler,
        # mở non-blocking để không chặn startup khi DB tạm thời unreachable.
        self._pool = None
        if ConnectionPool is not None:
            self._pool = ConnectionPool(
                self.database_url,
                min_size=1,
                max_size=int(os.getenv("DB_POOL_MAX_SIZE") or "10"),
                open=False,
                timeout=10,
                kwargs={"prepare_threshold": None, "connect_timeout": 10},
            )
            self._pool.open()

    def _connect(self):
        if self._pool is not None:
            return self._pool.connection()
        return psycopg.connect(self.database_url, prepare_threshold=None, connect_timeout=10)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()

    def execute_readonly(
        self,
        sql: str,
        *,
        max_rows: int | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        limit = max_rows or self.max_rows
        timeout = timeout_ms or self.timeout_ms
        ok, reason = validate_readonly_select(sql)
        if not ok:
            return self._error_result(reason)

        started = time.perf_counter()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(f"SET LOCAL statement_timeout = {int(timeout)}")
                    cur.execute(sql)
                    columns = [desc.name for desc in cur.description] if cur.description else []
                    fetched = cur.fetchmany(limit + 1) if columns else []
                conn.rollback()
        except Exception as exc:  # psycopg.Error + mọi lỗi runtime -> trả error, không raise
            return self._error_result(self._clean_error(exc), elapsed_ms=self._elapsed(started))

        truncated = len(fetched) > limit
        rows = [
            {col: _json_safe(val) for col, val in zip(columns, row)}
            for row in fetched[:limit]
        ]
        return {
            "ok": True,
            "error": "",
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "elapsed_ms": self._elapsed(started),
        }

    def _error_result(self, message: str, *, elapsed_ms: int = 0) -> dict[str, Any]:
        return {
            "ok": False,
            "error": message,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "elapsed_ms": elapsed_ms,
        }

    @staticmethod
    def _clean_error(exc: Exception) -> str:
        text = str(exc).strip()
        # Lỗi Postgres thường nhiều dòng (DETAIL/HINT) — giữ ngắn gọn cho UI + repair prompt.
        first = text.splitlines()[0] if text else exc.__class__.__name__
        return first[:500]

    @staticmethod
    def _elapsed(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
