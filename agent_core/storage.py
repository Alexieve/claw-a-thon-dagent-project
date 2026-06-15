from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional dependency for JSON-only local mode
    psycopg = None
    dict_row = None

try:
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover - optional; falls back to per-call connections
    ConnectionPool = None

from .constants import SCHEMA_PATH
from .utils import now_iso


class PostgresStorage:
    def __init__(self, database_url: str, *, schema_path: Path = SCHEMA_PATH) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required for DATABASE_URL storage")
        self.database_url = database_url
        self.schema_path = schema_path
        # Connection pool tái dùng kết nối tới Postgres remote (Supabase), tránh TCP+TLS
        # handshake mỗi thao tác. Mở non-blocking (wait=False) để không chặn startup khi DB
        # tạm thời unreachable; pool.connection() sẽ chờ tối đa `timeout` để lấy được kết nối.
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

    def bootstrap(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(self.schema_path.read_text(encoding="utf-8"))
            conn.commit()

    def load_candidates(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("select payload from knowledge_candidates")
                rows = cur.fetchall()
        return {"schema_version": 1, "candidates": {row["payload"]["id"]: row["payload"] for row in rows}}

    def save_candidates(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from knowledge_candidates")
                for candidate in data.get("candidates", {}).values():
                    self._upsert_candidate(cur, candidate)
            conn.commit()

    def load_knowledge_base(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("select payload from knowledge_records")
                rows = cur.fetchall()
        return {"schema_version": 1, "knowledge": {row["payload"]["id"]: row["payload"] for row in rows}}

    def save_knowledge_base(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from knowledge_records")
                for record in data.get("knowledge", {}).values():
                    self._upsert_knowledge(cur, record)
            conn.commit()

    def load_teaching_sessions(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("select payload from teaching_sessions")
                rows = cur.fetchall()
        return {"schema_version": 1, "sessions": {row["payload"]["id"]: row["payload"] for row in rows}}

    def save_teaching_sessions(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from teaching_sessions")
                for session in data.get("sessions", {}).values():
                    self._upsert_teaching_session(cur, session)
            conn.commit()

    def load_chat_sessions(self, *, user_id: str = "") -> dict[str, Any]:
        # Filter user_id ngay tại SQL (dùng index chat_sessions_user_id_idx) thay vì quét cả
        # bảng rồi lọc bằng Python. user_id rỗng -> trả toàn bộ session như cũ.
        query = "select payload from chat_sessions"
        params: tuple[Any, ...] = ()
        if user_id:
            query += " where user_id = %s"
            params = (user_id,)
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return {"schema_version": 1, "sessions": {row["payload"]["id"]: row["payload"] for row in rows}}

    def load_chat_session(self, session_id: str) -> dict[str, Any] | None:
        """Point lookup theo primary key thay vì quét toàn bảng. Trả về payload hoặc None."""
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("select payload from chat_sessions where id = %s", (session_id,))
                row = cur.fetchone()
        return row["payload"] if row else None

    def save_chat_sessions(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from chat_sessions")
                for session in data.get("sessions", {}).values():
                    self._upsert_chat_session(cur, session)
            conn.commit()

    def save_chat_session(self, session: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_chat_session(cur, session)
            conn.commit()

    # Point-upsert 1 record (không delete+reinsert cả bảng). Dùng cho luồng ghi đơn lẻ trong
    # app. Các save_* full-table phía trên vẫn được giữ cho scripts/reset_test_data.py (vốn dựa
    # vào delete-all để xoá record test khỏi DB).
    def save_knowledge_record(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_knowledge(cur, record)
            conn.commit()

    def save_candidate(self, candidate: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_candidate(cur, candidate)
            conn.commit()

    def save_teaching_session(self, session: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_teaching_session(cur, session)
            conn.commit()

    def save_data_dictionary_record(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_data_dictionary(cur, record)
            conn.commit()

    def save_question_example(self, example: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_question_example(cur, example)
            conn.commit()

    def load_data_dictionary(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("select payload from data_dictionary")
                rows = cur.fetchall()
        return {"schema_version": 1, "records": {row["payload"]["id"]: row["payload"] for row in rows}}

    def save_data_dictionary(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from data_dictionary")
                for record in data.get("records", {}).values():
                    self._upsert_data_dictionary(cur, record)
            conn.commit()

    def load_question_examples(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("select payload from question_examples")
                rows = cur.fetchall()
        return {"schema_version": 1, "examples": {row["payload"]["id"]: row["payload"] for row in rows}}

    def save_question_examples(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from question_examples")
                for example in data.get("examples", {}).values():
                    self._upsert_question_example(cur, example)
            conn.commit()

    def append_raw_event(self, event: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_raw_event(cur, event)
            conn.commit()

    def append_document_chunk(self, chunk: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_document_chunk(cur, chunk)
            conn.commit()

    def _connect(self):
        if self._pool is not None:
            return self._pool.connection()
        return psycopg.connect(self.database_url, prepare_threshold=None, connect_timeout=10)

    def _upsert_knowledge(self, cur, record: dict[str, Any]) -> None:
        cur.execute(
            """
            insert into knowledge_records (id, name, status, owner, domain, version, updated_at, payload)
            values (%s, %s, %s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            on conflict (id) do update set
              name = excluded.name,
              status = excluded.status,
              owner = excluded.owner,
              domain = excluded.domain,
              version = excluded.version,
              updated_at = excluded.updated_at,
              payload = excluded.payload
            """,
            (
                record["id"],
                record.get("name", ""),
                record.get("status", "approved"),
                record.get("owner", ""),
                record.get("domain", ""),
                int(record.get("version") or 1),
                record.get("updated_at") or now_iso(),
                json.dumps(record, ensure_ascii=False),
            ),
        )

    def _upsert_candidate(self, cur, candidate: dict[str, Any]) -> None:
        cur.execute(
            """
            insert into knowledge_candidates
              (id, name, status, target_knowledge_id, proposed_by, original_owner, created_at, payload)
            values (%s, %s, %s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            on conflict (id) do update set
              name = excluded.name,
              status = excluded.status,
              target_knowledge_id = excluded.target_knowledge_id,
              proposed_by = excluded.proposed_by,
              original_owner = excluded.original_owner,
              payload = excluded.payload
            """,
            (
                candidate["id"],
                candidate.get("name", ""),
                candidate.get("status", "pending_review"),
                candidate.get("target_knowledge_id") or None,
                candidate.get("proposed_by", ""),
                candidate.get("original_owner", ""),
                candidate.get("created_at") or now_iso(),
                json.dumps(candidate, ensure_ascii=False),
            ),
        )

    def _upsert_teaching_session(self, cur, session: dict[str, Any]) -> None:
        cur.execute(
            """
            insert into teaching_sessions
              (id, status, stakeholder, team, owner, created_at, updated_at, payload)
            values (%s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz, %s::jsonb)
            on conflict (id) do update set
              status = excluded.status,
              stakeholder = excluded.stakeholder,
              team = excluded.team,
              owner = excluded.owner,
              updated_at = excluded.updated_at,
              payload = excluded.payload
            """,
            (
                session["id"],
                session.get("status", "clarifying"),
                session.get("stakeholder", ""),
                session.get("team", ""),
                session.get("owner", ""),
                session.get("created_at") or now_iso(),
                session.get("updated_at") or now_iso(),
                json.dumps(session, ensure_ascii=False),
            ),
        )

    def _upsert_chat_session(self, cur, session: dict[str, Any]) -> None:
        cur.execute(
            """
            insert into chat_sessions
              (id, state, user_id, active_teaching_session_id, updated_at, payload)
            values (%s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            on conflict (id) do update set
              state = excluded.state,
              user_id = excluded.user_id,
              active_teaching_session_id = excluded.active_teaching_session_id,
              updated_at = excluded.updated_at,
              payload = excluded.payload
            """,
            (
                session["id"],
                session.get("state", "idle"),
                session.get("user_id", ""),
                session.get("active_teaching_session_id") or "",
                session.get("updated_at") or now_iso(),
                json.dumps(session, ensure_ascii=False),
            ),
        )

    def _upsert_raw_event(self, cur, event: dict[str, Any]) -> None:
        cur.execute(
            """
            insert into raw_events
              (id, source_type, stakeholder, team, document_id, status, raw_text, created_at, payload)
            values (%s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            on conflict (id) do update set payload = excluded.payload
            """,
            (
                event["id"],
                event.get("source_type", ""),
                event.get("stakeholder", ""),
                event.get("team", ""),
                event.get("document_id", ""),
                event.get("status", "parsed"),
                event.get("raw_text", ""),
                event.get("created_at") or now_iso(),
                json.dumps(event, ensure_ascii=False),
            ),
        )

    def _upsert_document_chunk(self, cur, chunk: dict[str, Any]) -> None:
        cur.execute(
            """
            insert into document_chunks (id, document_id, chunk_index, title, created_at, payload)
            values (%s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            on conflict (id) do update set payload = excluded.payload
            """,
            (
                chunk["id"],
                chunk.get("document_id", ""),
                int(chunk.get("chunk_index") or 0),
                chunk.get("title", ""),
                chunk.get("created_at") or now_iso(),
                json.dumps(chunk, ensure_ascii=False),
            ),
        )

    def _upsert_data_dictionary(self, cur, record: dict[str, Any]) -> None:
        cur.execute(
            """
            insert into data_dictionary
              (id, table_name, status, owner, updated_at, payload)
            values (%s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            on conflict (id) do update set
              table_name = excluded.table_name,
              status = excluded.status,
              owner = excluded.owner,
              updated_at = excluded.updated_at,
              payload = excluded.payload
            """,
            (
                record["id"],
                record.get("table", ""),
                record.get("status", "approved"),
                record.get("owner", ""),
                record.get("updated_at") or now_iso(),
                json.dumps(record, ensure_ascii=False),
            ),
        )

    def _upsert_question_example(self, cur, example: dict[str, Any]) -> None:
        cur.execute(
            """
            insert into question_examples
              (id, question, status, owner, updated_at, payload)
            values (%s, %s, %s, %s, %s::timestamptz, %s::jsonb)
            on conflict (id) do update set
              question = excluded.question,
              status = excluded.status,
              owner = excluded.owner,
              updated_at = excluded.updated_at,
              payload = excluded.payload
            """,
            (
                example["id"],
                example.get("question", ""),
                example.get("status", "approved"),
                example.get("owner", ""),
                example.get("updated_at") or now_iso(),
                json.dumps(example, ensure_ascii=False),
            ),
        )
