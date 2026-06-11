import copy
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional dependency for JSON-only local mode
    psycopg = None
    dict_row = None


DATA_DIR = Path(__file__).parent / "data"
RAW_EVENTS_PATH = DATA_DIR / "raw_events.jsonl"
CANDIDATES_PATH = DATA_DIR / "knowledge_candidates.json"
KNOWLEDGE_BASE_PATH = DATA_DIR / "knowledge_base.json"
DOCUMENT_CHUNKS_PATH = DATA_DIR / "document_chunks.jsonl"
TEACHING_SESSIONS_PATH = DATA_DIR / "teaching_sessions.json"
DATA_DICTIONARY_PATH = DATA_DIR / "data_dictionary.json"
QUESTION_EXAMPLES_PATH = DATA_DIR / "question_examples.json"
SCHEMA_PATH = Path(__file__).parent / "db" / "schema.sql"

ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
ALLOWED_KINDS = {"metric", "term", "dimension", "business_rule", "synonym"}
ALLOWED_CANDIDATE_STATUSES = {"pending_review", "pending_change", "approved", "rejected", "conflict"}
ALLOWED_TEACHING_SESSION_STATUSES = {"clarifying", "awaiting_confirmation", "committed", "pending_approval", "cancelled"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_lookup(value: Any) -> str:
    return normalize_text(value).casefold()


def extract_acronyms(text: str) -> list[str]:
    seen: set[str] = set()
    acronyms: list[str] = []
    for match in ACRONYM_PATTERN.findall(text or ""):
        if match not in seen:
            seen.add(match)
            acronyms.append(match)
    return acronyms


def canonicalize_name_and_aliases(name: Any) -> tuple[str, list[str]]:
    cleaned = normalize_text(name)
    if not cleaned:
        return "", []

    match = re.match(r"^([A-Z][A-Z0-9]{1,9})\b(?:\s*[\(\-:/]\s*(.+?)\s*\)?$)?", cleaned)
    if not match:
        return cleaned, []

    canonical = match.group(1)
    aliases = []
    if cleaned != canonical:
        aliases.append(cleaned)
    expanded = normalize_text(match.group(2) or "").strip("() ")
    if expanded:
        aliases.append(expanded)
    return canonical, unique_values(aliases)


def empty_candidates() -> dict[str, Any]:
    return {"schema_version": 1, "candidates": {}}


def empty_knowledge_base() -> dict[str, Any]:
    return {"schema_version": 1, "knowledge": {}}


def empty_teaching_sessions() -> dict[str, Any]:
    return {"schema_version": 1, "sessions": {}}


def empty_data_dictionary() -> dict[str, Any]:
    return {"schema_version": 1, "records": {}}


def empty_question_examples() -> dict[str, Any]:
    return {"schema_version": 1, "examples": {}}


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|[\n;]+", text or "")
    return [normalize_text(part.strip(" .!?")) for part in parts if normalize_text(part.strip(" .!?"))]


def unique_values(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = normalize_text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def normalize_confidence(value: Any, default: float = 0.5) -> float:
    if isinstance(value, str):
        mapped = {
            "high": 0.85,
            "medium": 0.6,
            "low": 0.35,
            "certain": 0.9,
            "uncertain": 0.35,
        }.get(value.strip().casefold())
        if mapped is not None:
            return mapped
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 120) -> list[str]:
    cleaned = normalize_text(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end].strip())
        if end == len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


def candidate_template(
    *,
    source_event_id: str,
    kind: str,
    name: str,
    definition: str = "",
    paraphrases: list[str] | None = None,
    formula: str | None = None,
    conditions: list[str] | None = None,
    domain: str = "",
    owner: str = "",
    confidence: float = 0.5,
) -> dict[str, Any]:
    candidate_id = new_id("cand")
    return {
        "id": candidate_id,
        "source_event_id": source_event_id,
        "kind": kind if kind in ALLOWED_KINDS else "term",
        "name": normalize_text(name),
        "definition": normalize_text(definition),
        "paraphrases": unique_values(paraphrases or []),
        "formula": normalize_text(formula) or None,
        "conditions": unique_values(conditions or []),
        "domain": normalize_text(domain),
        "owner": normalize_text(owner),
        "confidence": normalize_confidence(confidence),
        "status": "pending_review",
        "conflict_with": "",
        "created_at": now_iso(),
    }


class KnowledgeParser:
    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "")

    def parse(
        self,
        *,
        text: str,
        source_event_id: str,
        stakeholder: str = "",
        team: str = "",
        domain: str = "",
        owner: str = "",
    ) -> list[dict[str, Any]]:
        cleaned = normalize_text(text)
        if not cleaned:
            return []

        if self.api_key and self.base_url and self.model:
            llm_candidates = self._parse_with_llm(
                text=cleaned,
                source_event_id=source_event_id,
                domain=domain or team,
                owner=owner or stakeholder,
            )
            if llm_candidates:
                return llm_candidates

        return self._parse_deterministic(
            text=cleaned,
            source_event_id=source_event_id,
            domain=domain or team,
            owner=owner or stakeholder,
        )

    def _parse_with_llm(
        self,
        *,
        text: str,
        source_event_id: str,
        domain: str,
        owner: str,
    ) -> list[dict[str, Any]]:
        prompt = (
            "Extract business knowledge from the user's Vietnamese/English text. "
            "Return only JSON with an 'items' array. Do not invent facts. "
            "Allowed kind values: metric, term, dimension, business_rule, synonym. "
            "Each item fields: kind, name, definition, paraphrases, formula, conditions, domain, owner, confidence. "
            "If a field is not explicit in the text, use an empty string, null, or empty array.\n\n"
            f"Text:\n{text}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a strict structured information extraction engine."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
        except (error.URLError, TimeoutError, ValueError):
            return []

        try:
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return []

        items = parsed.get("items", [])
        if not isinstance(items, list):
            return []

        candidates: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = normalize_text(item.get("name", ""))
            definition = normalize_text(item.get("definition", ""))
            if not name and not definition:
                continue
            candidates.append(
                candidate_template(
                    source_event_id=source_event_id,
                    kind=str(item.get("kind") or "term"),
                    name=name or definition[:60],
                    definition=definition,
                    paraphrases=item.get("paraphrases") if isinstance(item.get("paraphrases"), list) else [],
                    formula=item.get("formula"),
                    conditions=item.get("conditions") if isinstance(item.get("conditions"), list) else [],
                    domain=normalize_text(item.get("domain")) or domain,
                    owner=normalize_text(item.get("owner")) or owner,
                    confidence=normalize_confidence(item.get("confidence"), default=0.7),
                )
            )
        return candidates

    def rank_knowledge(self, *, query: str, records: list[dict[str, Any]]) -> list[str] | None:
        cleaned = normalize_text(query)
        if not cleaned or not records:
            return None
        if not (self.api_key and self.base_url and self.model):
            return None

        compact_records = [
            {
                "id": record.get("id", ""),
                "name": record.get("name", ""),
                "definition": record.get("canonical_definition", ""),
                "paraphrases": record.get("paraphrases", []),
                "domain": record.get("domain", ""),
                "owner": record.get("owner", ""),
            }
            for record in records
        ]
        prompt = (
            "Rank the approved business knowledge records that are relevant to the user's query. "
            "Return only JSON with an 'ids' array. Include only IDs from the provided records. "
            "Return an empty array if no record is relevant.\n\n"
            f"Query:\n{cleaned}\n\n"
            f"Records:\n{json.dumps(compact_records, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a strict knowledge retrieval ranker."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

        ids = parsed.get("ids")
        if not isinstance(ids, list):
            return None
        valid_ids = {record["id"] for record in compact_records}
        return [str(item) for item in ids if str(item) in valid_ids]

    def _parse_deterministic(
        self,
        *,
        text: str,
        source_event_id: str,
        domain: str,
        owner: str,
    ) -> list[dict[str, Any]]:
        sentences = split_sentences(text)
        acronyms = extract_acronyms(text)
        grouped: dict[str, dict[str, Any]] = {}

        for sentence in sentences:
            match = re.search(
                r"\b([A-Z][A-Z0-9]{1,9})\b\s*(?:là|la|means|mean|=|:)\s*(.+)",
                sentence,
                flags=re.IGNORECASE,
            )
            if match:
                name = match.group(1).upper()
                definition = normalize_text(match.group(2))
                grouped.setdefault(
                    name,
                    candidate_template(
                        source_event_id=source_event_id,
                        kind="metric",
                        name=name,
                        definition=definition,
                        domain=domain,
                        owner=owner,
                        confidence=0.72,
                    ),
                )
                grouped[name]["definition"] = grouped[name]["definition"] or definition

        if not grouped and not acronyms:
            for sentence in sentences:
                match = re.search(r"^(.{2,60}?)\s*(?:là|means|=|:)\s*(.+)", sentence, flags=re.IGNORECASE)
                if not match:
                    continue
                name = normalize_text(match.group(1))
                definition = normalize_text(match.group(2))
                if name and definition:
                    grouped[name] = candidate_template(
                        source_event_id=source_event_id,
                        kind="term",
                        name=name,
                        definition=definition,
                        domain=domain,
                        owner=owner,
                        confidence=0.62,
                    )
                    break

        for acronym in acronyms:
            grouped.setdefault(
                acronym,
                candidate_template(
                    source_event_id=source_event_id,
                    kind="metric",
                    name=acronym,
                    definition="",
                    domain=domain,
                    owner=owner,
                    confidence=0.3,
                ),
            )

        paraphrases = self._extract_paraphrases(sentences)
        conditions = self._extract_conditions(sentences)
        formula = self._extract_formula(sentences)
        if grouped:
            first_key = next(iter(grouped))
            grouped[first_key]["paraphrases"] = unique_values(grouped[first_key]["paraphrases"] + paraphrases)
            grouped[first_key]["conditions"] = unique_values(grouped[first_key]["conditions"] + conditions)
            if formula and not grouped[first_key]["formula"]:
                grouped[first_key]["formula"] = formula

        return list(grouped.values())

    def _extract_paraphrases(self, sentences: list[str]) -> list[str]:
        values: list[str] = []
        for sentence in sentences:
            for pattern in [
                r"(?:hay gọi là|còn gọi là|được gọi là|aka|also called)\s+(.+)",
                r"(?:paraphrase|synonym|alias)\s*(?:là|=|:)\s*(.+)",
            ]:
                match = re.search(pattern, sentence, flags=re.IGNORECASE)
                if match:
                    values.append(match.group(1))
        return unique_values(values)

    def _extract_conditions(self, sentences: list[str]) -> list[str]:
        markers = ["nếu", "khi", "chỉ", "trong vòng", "condition", "when", "only"]
        return unique_values([sentence for sentence in sentences if any(marker in sentence.casefold() for marker in markers)])

    def _extract_formula(self, sentences: list[str]) -> str | None:
        markers = ["công thức", "formula", "tính bằng", "calculated as"]
        for sentence in sentences:
            if any(marker in sentence.casefold() for marker in markers):
                return sentence
        return None


class PostgresStorage:
    def __init__(self, database_url: str, *, schema_path: Path = SCHEMA_PATH) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required for DATABASE_URL storage")
        self.database_url = database_url
        self.schema_path = schema_path

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
        return psycopg.connect(self.database_url)

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


class KnowledgeStore:
    def __init__(
        self,
        *,
        raw_events_path: Path | str = RAW_EVENTS_PATH,
        candidates_path: Path | str = CANDIDATES_PATH,
        knowledge_base_path: Path | str = KNOWLEDGE_BASE_PATH,
        document_chunks_path: Path | str = DOCUMENT_CHUNKS_PATH,
        teaching_sessions_path: Path | str = TEACHING_SESSIONS_PATH,
        data_dictionary_path: Path | str = DATA_DICTIONARY_PATH,
        question_examples_path: Path | str = QUESTION_EXAMPLES_PATH,
        database_url: str | None = None,
        parser: KnowledgeParser | None = None,
    ) -> None:
        self.raw_events_path = Path(raw_events_path)
        self.candidates_path = Path(candidates_path)
        self.knowledge_base_path = Path(knowledge_base_path)
        self.document_chunks_path = Path(document_chunks_path)
        self.teaching_sessions_path = Path(teaching_sessions_path)
        self.data_dictionary_path = Path(data_dictionary_path)
        self.question_examples_path = Path(question_examples_path)
        self.database_url = normalize_text(database_url if database_url is not None else os.getenv("DATABASE_URL"))
        self.db = PostgresStorage(self.database_url) if self.database_url else None
        self.parser = parser or KnowledgeParser()

    def bootstrap(self) -> None:
        if self.db:
            self.db.bootstrap()
            return
        self.candidates_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.candidates_path.exists():
            self._save_json(self.candidates_path, empty_candidates())
        if not self.knowledge_base_path.exists():
            self._save_json(self.knowledge_base_path, empty_knowledge_base())
        if not self.raw_events_path.exists():
            self.raw_events_path.write_text("", encoding="utf-8")
        if not self.document_chunks_path.exists():
            self.document_chunks_path.write_text("", encoding="utf-8")
        if not self.teaching_sessions_path.exists():
            self._save_json(self.teaching_sessions_path, empty_teaching_sessions())
        if not self.data_dictionary_path.exists():
            self._save_json(self.data_dictionary_path, empty_data_dictionary())
        if not self.question_examples_path.exists():
            self._save_json(self.question_examples_path, empty_question_examples())

    def append_raw_event(
        self,
        *,
        source_type: str,
        raw_text: str,
        stakeholder: str = "",
        team: str = "",
        document_id: str = "",
        status: str = "parsed",
    ) -> dict[str, Any]:
        cleaned = normalize_text(raw_text)
        if not cleaned:
            raise ValueError("Thiếu nội dung cần dạy")
        event = {
            "id": new_id("evt"),
            "source_type": source_type,
            "raw_text": cleaned,
            "stakeholder": normalize_text(stakeholder),
            "team": normalize_text(team),
            "document_id": normalize_text(document_id),
            "created_at": now_iso(),
            "status": status,
        }
        if self.db:
            self.db.append_raw_event(event)
        else:
            self._append_jsonl(self.raw_events_path, event)
        return copy.deepcopy(event)

    def storage_status(self) -> dict[str, Any]:
        return {
            "backend": "postgres" if self.db else "json",
            "database_configured": bool(self.db),
        }

    def teach_text(
        self,
        *,
        text: str,
        stakeholder: str = "",
        team: str = "",
        domain: str = "",
        owner: str = "",
        source_type: str = "manual_text",
        document_id: str = "",
    ) -> dict[str, Any]:
        event = self.append_raw_event(
            source_type=source_type,
            raw_text=text,
            stakeholder=stakeholder,
            team=team,
            document_id=document_id,
        )
        candidates = self.parser.parse(
            text=event["raw_text"],
            source_event_id=event["id"],
            stakeholder=stakeholder,
            team=team,
            domain=domain,
            owner=owner,
        )
        if not candidates:
            event["status"] = "parse_failed"
            return {"raw_event": event, "knowledge_created": [], "change_requests": [], "candidates": []}

        processed = [
            self._commit_confirmed_candidate(
                candidate,
                proposed_by=owner or stakeholder,
                source_event_id=event["id"],
            )
            for candidate in candidates
        ]
        knowledge_created = [item["knowledge"] for item in processed if item.get("result") == "created"]
        change_requests = [item["candidate"] for item in processed if item.get("result") == "pending_change"]
        return {
            "raw_event": event,
            "knowledge_created": knowledge_created,
            "change_requests": change_requests,
            "candidates": change_requests,
        }

    def ingest_document(
        self,
        *,
        text: str,
        title: str = "",
        stakeholder: str = "",
        team: str = "",
        domain: str = "",
        owner: str = "",
    ) -> dict[str, Any]:
        cleaned = normalize_text(text)
        if not cleaned:
            raise ValueError("Thiếu nội dung file")
        document_id = new_id("doc")
        chunks = []
        all_knowledge_created: list[dict[str, Any]] = []
        all_change_requests: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunk_text(cleaned)):
            chunk_record = {
                "id": new_id("chunk"),
                "document_id": document_id,
                "title": normalize_text(title),
                "chunk_index": index,
                "text": chunk,
                "created_at": now_iso(),
            }
            if self.db:
                self.db.append_document_chunk(chunk_record)
            else:
                self._append_jsonl(self.document_chunks_path, chunk_record)
            chunks.append(chunk_record)
            taught = self.teach_text(
                text=chunk,
                stakeholder=stakeholder,
                team=team,
                domain=domain,
                owner=owner,
                source_type="document",
                document_id=document_id,
            )
            all_knowledge_created.extend(taught["knowledge_created"])
            all_change_requests.extend(taught["change_requests"])

        return {
            "document_id": document_id,
            "chunks": chunks,
            "knowledge_created": all_knowledge_created,
            "change_requests": all_change_requests,
            "candidates": all_change_requests,
        }

    def start_teach_session(
        self,
        *,
        message: str,
        stakeholder: str = "",
        team: str = "",
        domain: str = "",
        owner: str = "",
    ) -> dict[str, Any]:
        cleaned = normalize_text(message)
        if not cleaned:
            raise ValueError("Thiếu nội dung teaching message")

        session = {
            "id": new_id("teach"),
            "status": "clarifying",
            "messages": [{"role": "user", "content": cleaned, "created_at": now_iso()}],
            "draft": {},
            "stakeholder": normalize_text(stakeholder),
            "team": normalize_text(team),
            "domain": normalize_text(domain),
            "owner": normalize_text(owner or stakeholder),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        session = self._refresh_teaching_session(session)
        self._save_teaching_session(session)
        return self._teaching_session_response(session)

    def append_teach_message(self, *, session_id: str, message: str) -> dict[str, Any]:
        session = self._get_teaching_session(session_id)
        if session.get("status") in {"committed", "pending_approval", "cancelled"}:
            raise ValueError(f"Teaching session đã kết thúc: {session_id}")

        cleaned = normalize_text(message)
        if not cleaned:
            raise ValueError("Thiếu nội dung teaching message")
        session["messages"].append({"role": "user", "content": cleaned, "created_at": now_iso()})
        session = self._refresh_teaching_session(session)
        self._save_teaching_session(session)
        return self._teaching_session_response(session)

    def summarize_teach_session(self, *, session_id: str) -> dict[str, Any]:
        session = self._get_teaching_session(session_id)
        session = self._refresh_teaching_session(session, force_confirmation=True)
        self._save_teaching_session(session)
        return self._teaching_session_response(session)

    def confirm_teach_session(self, *, session_id: str, decision: str = "confirm") -> dict[str, Any]:
        session = self._get_teaching_session(session_id)
        normalized_decision = normalize_lookup(decision)
        if normalized_decision in {"cancel", "reject"}:
            session["status"] = "cancelled"
            session["updated_at"] = now_iso()
            self._save_teaching_session(session)
            return {"session": copy.deepcopy(session), "knowledge_created": [], "change_requests": []}
        if normalized_decision != "confirm":
            raise ValueError("decision phải là confirm, cancel hoặc reject")

        draft = session.get("draft") if isinstance(session.get("draft"), dict) else {}
        if not draft or not normalize_text(draft.get("name")):
            raise ValueError("Teaching session chưa có draft knowledge để confirm")

        raw_text = "\n".join(message["content"] for message in session.get("messages", []) if message.get("role") == "user")
        event = self.append_raw_event(
            source_type="teaching_session",
            raw_text=raw_text,
            stakeholder=session.get("stakeholder", ""),
            team=session.get("team", ""),
            document_id=session["id"],
        )
        draft["source_event_id"] = event["id"]
        processed = self._commit_confirmed_candidate(
            draft,
            proposed_by=session.get("owner") or session.get("stakeholder", ""),
            source_event_id=event["id"],
        )
        knowledge_created = [processed["knowledge"]] if processed.get("result") == "created" else []
        change_requests = [processed["candidate"]] if processed.get("result") == "pending_change" else []
        session["status"] = "pending_approval" if change_requests else "committed"
        session["raw_event_id"] = event["id"]
        session["knowledge_created_ids"] = [item["id"] for item in knowledge_created]
        session["change_request_ids"] = [item["id"] for item in change_requests]
        session["updated_at"] = now_iso()
        self._save_teaching_session(session)
        return {
            "session": copy.deepcopy(session),
            "raw_event": event,
            "knowledge_created": knowledge_created,
            "change_requests": change_requests,
        }

    def add_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        data = self._load_candidates()
        normalized = self._normalize_candidate(candidate)
        data["candidates"][normalized["id"]] = normalized
        self._save_json(self.candidates_path, data)
        return copy.deepcopy(normalized)

    def list_candidates(self, status: str = "") -> list[dict[str, Any]]:
        data = self._load_candidates()
        normalized_status = normalize_lookup(status)
        candidates = []
        for candidate in data["candidates"].values():
            if normalized_status and normalize_lookup(candidate.get("status")) != normalized_status:
                continue
            candidates.append(copy.deepcopy(candidate))
        return sorted(candidates, key=lambda item: item.get("created_at", ""), reverse=True)

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        return copy.deepcopy(self._load_candidates()["candidates"].get(candidate_id))

    def review_candidate(
        self,
        *,
        candidate_id: str,
        decision: str,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._load_candidates()
        candidate = data["candidates"].get(candidate_id)
        if not candidate:
            raise ValueError(f"Không tìm thấy candidate: {candidate_id}")

        if updates:
            candidate.update(self._editable_candidate_updates(updates))
            candidate = self._normalize_candidate(candidate)
            if candidate.get("target_knowledge_id"):
                existing = self._load_knowledge_base()["knowledge"].get(candidate["target_knowledge_id"])
                if existing:
                    before = self._knowledge_snapshot(existing)
                    after = self._build_after_snapshot(existing, candidate)
                    candidate["before"] = before
                    candidate["after"] = after
                    candidate["change_summary"] = self._build_change_summary(before, after)

        normalized_decision = normalize_lookup(decision)
        if normalized_decision == "reject":
            candidate["status"] = "rejected"
            data["candidates"][candidate_id] = candidate
            self._save_json(self.candidates_path, data)
            return {"candidate": copy.deepcopy(candidate), "knowledge": None}

        if normalized_decision != "approve":
            raise ValueError("decision phải là approve hoặc reject")

        knowledge = self._approve_candidate(candidate)
        candidate["status"] = "approved" if knowledge else "conflict"
        if knowledge:
            candidate["conflict_with"] = ""
        data["candidates"][candidate_id] = candidate
        self._save_json(self.candidates_path, data)
        return {"candidate": copy.deepcopy(candidate), "knowledge": copy.deepcopy(knowledge)}

    def search_knowledge(self, query: str = "") -> list[dict[str, Any]]:
        data = self._load_knowledge_base()
        normalized_query = normalize_lookup(query)
        all_records = []
        deterministic_records = []
        exact_acronym_records = []
        query_acronyms = extract_acronyms(query)
        for record in data["knowledge"].values():
            if record.get("status") != "approved":
                continue
            record_copy = copy.deepcopy(record)
            all_records.append(record_copy)
            names = [record.get("name", ""), *record.get("paraphrases", [])]
            if query_acronyms and any(
                self._contains_term(name, acronym) for acronym in query_acronyms for name in names
            ):
                exact_acronym_records.append(record_copy)
            haystack = " ".join(
                [
                    record.get("name", ""),
                    record.get("canonical_definition", ""),
                    record.get("logic", ""),
                    record.get("domain", ""),
                    record.get("owner", ""),
                    " ".join(record.get("paraphrases", [])),
                    " ".join(record.get("conditions", [])),
                    " ".join(record.get("examples", [])),
                ]
            )
            if not normalized_query or normalized_query in normalize_lookup(haystack):
                deterministic_records.append(record_copy)

        if query_acronyms and exact_acronym_records:
            return sorted(exact_acronym_records, key=lambda item: item.get("name", ""))

        if normalized_query:
            candidate_pool = deterministic_records if deterministic_records else all_records
            ranked_ids = self.parser.rank_knowledge(query=query, records=candidate_pool)
            if ranked_ids is not None:
                by_id = {record["id"]: record for record in candidate_pool}
                return [copy.deepcopy(by_id[record_id]) for record_id in ranked_ids if record_id in by_id]

        return sorted(deterministic_records, key=lambda item: item.get("name", ""))

    def add_data_dictionary(
        self,
        *,
        table: str,
        columns: list[dict[str, Any]] | None = None,
        description: str = "",
        relationships: list[dict[str, Any]] | None = None,
        owner: str = "",
        status: str = "approved",
    ) -> dict[str, Any]:
        record = self._normalize_data_dictionary(
            {
                "id": new_id("dict"),
                "table": table,
                "description": description,
                "columns": columns or [],
                "relationships": relationships or [],
                "owner": owner,
                "status": status,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
        data = self._load_data_dictionary()
        data["records"][record["id"]] = record
        self._save_json(self.data_dictionary_path, data)
        return copy.deepcopy(record)

    def list_data_dictionary(self) -> list[dict[str, Any]]:
        records = [copy.deepcopy(item) for item in self._load_data_dictionary()["records"].values()]
        return sorted(records, key=lambda item: item.get("table", ""))

    def search_data_dictionary(self, query: str = "") -> list[dict[str, Any]]:
        normalized_query = normalize_lookup(query)
        records = []
        for record in self._load_data_dictionary()["records"].values():
            if record.get("status") != "approved":
                continue
            record_copy = copy.deepcopy(record)
            if not normalized_query or normalized_query in normalize_lookup(self._dictionary_haystack(record)):
                records.append(record_copy)
                continue
            query_terms = self._extract_question_terms(query)
            if any(self._dictionary_matches_term(record, term) for term in query_terms):
                records.append(record_copy)
        return sorted(records, key=lambda item: item.get("table", ""))

    def add_question_example(
        self,
        *,
        question: str,
        sql: str,
        explanation: str = "",
        concepts: list[str] | None = None,
        used_tables: list[str] | None = None,
        owner: str = "",
        status: str = "approved",
    ) -> dict[str, Any]:
        example = self._normalize_question_example(
            {
                "id": new_id("qex"),
                "question": question,
                "sql": sql,
                "explanation": explanation,
                "concepts": concepts or [],
                "used_tables": used_tables or [],
                "owner": owner,
                "status": status,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
        data = self._load_question_examples()
        data["examples"][example["id"]] = example
        self._save_json(self.question_examples_path, data)
        return copy.deepcopy(example)

    def list_question_examples(self) -> list[dict[str, Any]]:
        examples = [copy.deepcopy(item) for item in self._load_question_examples()["examples"].values()]
        return sorted(examples, key=lambda item: item.get("updated_at", ""), reverse=True)

    def search_question_examples(self, query: str = "") -> list[dict[str, Any]]:
        normalized_query = normalize_lookup(query)
        query_terms = self._extract_question_terms(query)
        matches = []
        for example in self._load_question_examples()["examples"].values():
            if example.get("status") != "approved":
                continue
            haystack = " ".join(
                [
                    example.get("question", ""),
                    example.get("explanation", ""),
                    " ".join(example.get("concepts", [])),
                    " ".join(example.get("used_tables", [])),
                ]
            )
            if not normalized_query or normalized_query in normalize_lookup(haystack):
                matches.append(copy.deepcopy(example))
                continue
            example_terms = {normalize_lookup(term) for term in self._extract_question_terms(haystack)}
            overlap = [term for term in query_terms if normalize_lookup(term) in example_terms]
            if overlap:
                item = copy.deepcopy(example)
                item["_match_score"] = len(overlap)
                matches.append(item)
        return sorted(matches, key=lambda item: (int(item.get("_match_score") or 0), item.get("updated_at", "")), reverse=True)

    def ask_data_question(self, question: str) -> dict[str, Any]:
        cleaned = normalize_text(question)
        if not cleaned:
            raise ValueError("Thiếu câu hỏi nghiệp vụ")

        analysis = self.analyze_text(cleaned)
        known = analysis["known"]
        detected_concepts = unique_values([*analysis["detected_terms"], *self._extract_question_terms(cleaned)])
        missing_knowledge = analysis["unknown"]
        dictionary_matches = self.search_data_dictionary(cleaned)
        example_matches = self.search_question_examples(cleaned)

        if missing_knowledge:
            return {
                "status": "needs_knowledge",
                "question": cleaned,
                "detected_concepts": detected_concepts,
                "known_knowledge": known,
                "missing": [
                    {
                        "type": "domain_knowledge",
                        "concept": concept,
                        "question": f"{concept} nghĩa là gì trong nghiệp vụ?",
                    }
                    for concept in missing_knowledge
                ],
                "dictionary": dictionary_matches,
                "examples": example_matches,
                "answer": "Tôi chưa đủ Domain Knowledge để hiểu câu hỏi này.",
            }

        if not dictionary_matches:
            missing = self._build_missing_dictionary_items(cleaned, known, detected_concepts)
            return {
                "status": "needs_dictionary",
                "question": cleaned,
                "detected_concepts": detected_concepts,
                "known_knowledge": known,
                "missing": missing,
                "dictionary": [],
                "examples": example_matches,
                "answer": "Tôi đã tìm được knowledge nghiệp vụ liên quan, nhưng chưa đủ data dictionary để sinh SQL.",
            }

        if example_matches:
            example = example_matches[0]
            return {
                "status": "sql_draft",
                "question": cleaned,
                "detected_concepts": detected_concepts,
                "sql": example.get("sql", ""),
                "explanation": self._build_sql_explanation(known, dictionary_matches, example),
                "used_knowledge_ids": [item["id"] for item in known],
                "used_dictionary_ids": [item["id"] for item in dictionary_matches],
                "used_example_ids": [example["id"]],
                "knowledge": known,
                "dictionary": dictionary_matches,
                "examples": example_matches,
                "answer": "Tôi tìm được question example phù hợp và tạo SQL draft từ example đã approved.",
            }

        return {
            "status": "needs_example",
            "question": cleaned,
            "detected_concepts": detected_concepts,
            "known_knowledge": known,
            "dictionary": dictionary_matches,
            "examples": [],
            "missing": [
                {
                    "type": "question_example",
                    "concept": cleaned,
                    "question": "Chưa có SQL mẫu đã được confirm cho kiểu câu hỏi này.",
                }
            ],
            "answer": "Tôi đã có data dictionary liên quan, nhưng cần question example hoặc LLM SQL generator trước khi sinh SQL an toàn.",
        }

    def analyze_text(self, text: str) -> dict[str, Any]:
        cleaned = normalize_text(text)
        if not cleaned:
            return {"known": [], "unknown": [], "pending": [], "conflicts": [], "detected_terms": []}

        detected = extract_acronyms(cleaned)
        known: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        seen_known: set[str] = set()

        for record in self.search_knowledge():
            names = [record.get("name", ""), *record.get("paraphrases", [])]
            if any(self._contains_term(cleaned, name) for name in names):
                if record["id"] not in seen_known:
                    seen_known.add(record["id"])
                    known.append(record)
                    detected.append(record.get("name", ""))

        for candidate in self.list_candidates():
            if not self._contains_term(cleaned, candidate.get("name", "")):
                continue
            if candidate.get("status") == "conflict":
                conflicts.append(candidate)
            elif candidate.get("status") in {"pending_review", "pending_change"}:
                pending.append(candidate)

        known_names = {normalize_lookup(record.get("name")) for record in known}
        candidate_names = {normalize_lookup(item.get("name")) for item in [*pending, *conflicts]}
        unknown = [
            term
            for term in unique_values(detected)
            if normalize_lookup(term) not in known_names and normalize_lookup(term) not in candidate_names
        ]
        return {
            "known": known,
            "unknown": unknown,
            "pending": pending,
            "conflicts": conflicts,
            "detected_terms": unique_values(detected),
        }

    def _refresh_teaching_session(self, session: dict[str, Any], *, force_confirmation: bool = False) -> dict[str, Any]:
        text = "\n".join(message["content"] for message in session.get("messages", []) if message.get("role") == "user")
        candidates = self.parser.parse(
            text=text,
            source_event_id=session["id"],
            stakeholder=session.get("stakeholder", ""),
            team=session.get("team", ""),
            domain=session.get("domain", ""),
            owner=session.get("owner", ""),
        )
        draft = candidates[0] if candidates else {}
        if draft:
            existing = self._find_knowledge_by_name(draft.get("name", ""))
            draft["existing_knowledge"] = bool(existing)
            draft["target_knowledge_id"] = existing["id"] if existing else ""
            session["draft"] = draft
            if force_confirmation or (draft.get("definition") and normalize_confidence(draft.get("confidence")) >= 0.5):
                session["status"] = "awaiting_confirmation"
            else:
                session["status"] = "clarifying"
        else:
            session["draft"] = {}
            session["status"] = "clarifying"
        session["updated_at"] = now_iso()
        return session

    def _teaching_session_response(self, session: dict[str, Any]) -> dict[str, Any]:
        response = {"session": copy.deepcopy(session), "session_id": session["id"], "status": session["status"]}
        if session.get("draft"):
            response["draft"] = copy.deepcopy(session["draft"])
        if session["status"] == "awaiting_confirmation":
            response["summary"] = self._draft_summary(session.get("draft", {}))
            response["confirmation_prompt"] = "Bạn confirm nội dung này để ghi vào knowledge base chứ?"
        else:
            response["question"] = self._next_teaching_question(session.get("draft", {}))
        return response

    def _draft_summary(self, draft: dict[str, Any]) -> dict[str, Any]:
        return {
            "term": draft.get("name", ""),
            "definition": draft.get("definition", ""),
            "logic": draft.get("logic", ""),
            "domain": draft.get("domain", ""),
            "owner": draft.get("owner", ""),
            "examples": draft.get("examples", []),
            "paraphrases": draft.get("paraphrases", []),
            "formula": draft.get("formula"),
            "conditions": draft.get("conditions", []),
            "existing_knowledge": bool(draft.get("existing_knowledge")),
        }

    def _next_teaching_question(self, draft: dict[str, Any]) -> str:
        if not draft:
            return "Bạn đang muốn dạy term hoặc metric nào? Hãy nêu tên và định nghĩa ngắn gọn."
        if not normalize_text(draft.get("definition")):
            return f"{draft.get('name')} nghĩa là gì trong nghiệp vụ?"
        if not normalize_text(draft.get("domain")):
            return f"{draft.get('name')} thuộc domain hoặc team nào?"
        return "Bạn có ví dụ hoặc điều kiện áp dụng nào cần thêm trước khi confirm không?"

    def _get_teaching_session(self, session_id: str) -> dict[str, Any]:
        session = self._load_teaching_sessions()["sessions"].get(normalize_text(session_id))
        if not session:
            raise ValueError(f"Không tìm thấy teaching session: {session_id}")
        return copy.deepcopy(session)

    def _save_teaching_session(self, session: dict[str, Any]) -> None:
        if session.get("status") not in ALLOWED_TEACHING_SESSION_STATUSES:
            session["status"] = "clarifying"
        data = self._load_teaching_sessions()
        data["sessions"][session["id"]] = copy.deepcopy(session)
        self._save_json(self.teaching_sessions_path, data)

    def _approve_candidate(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        if candidate.get("status") == "pending_change" or candidate.get("target_knowledge_id"):
            return self._apply_change_candidate(candidate)

        existing = self._find_knowledge_by_name(candidate["name"])
        if existing:
            change = self._create_change_candidate(
                candidate,
                existing=existing,
                proposed_by=candidate.get("owner", ""),
                save=False,
            )
            return self._apply_change_candidate(change)

        return self._create_knowledge_from_candidate(candidate)

    def _commit_confirmed_candidate(
        self,
        candidate: dict[str, Any],
        *,
        proposed_by: str = "",
        source_event_id: str = "",
    ) -> dict[str, Any]:
        normalized = self._normalize_candidate({**candidate, "source_event_id": source_event_id or candidate.get("source_event_id")})
        existing = self._find_knowledge_by_name(normalized["name"])
        if existing:
            change = self._create_change_candidate(normalized, existing=existing, proposed_by=proposed_by)
            return {"result": "pending_change", "candidate": change, "knowledge": None}
        knowledge = self._create_knowledge_from_candidate(normalized, created_by=proposed_by)
        return {"result": "created", "candidate": None, "knowledge": knowledge}

    def _create_knowledge_from_candidate(
        self,
        candidate: dict[str, Any],
        *,
        created_by: str = "",
    ) -> dict[str, Any]:
        base = self._load_knowledge_base()
        owner = normalize_text(candidate.get("owner")) or normalize_text(created_by)
        record = {
            "id": new_id("kn"),
            "kind": candidate.get("kind") if candidate.get("kind") != "synonym" else "term",
            "name": candidate["name"],
            "canonical_definition": candidate.get("definition", ""),
            "logic": normalize_text(candidate.get("logic")),
            "examples": unique_values(candidate.get("examples", [])),
            "paraphrases": unique_values(candidate.get("paraphrases", [])),
            "formula": candidate.get("formula"),
            "conditions": unique_values(candidate.get("conditions", [])),
            "domain": candidate.get("domain", ""),
            "owner": owner,
            "created_by": normalize_text(created_by) or owner,
            "confidence": normalize_confidence(candidate.get("confidence"), default=0.0),
            "version": 1,
            "status": "approved",
            "evidence_event_ids": unique_values([candidate["source_event_id"]]),
            "candidate_ids": unique_values([candidate["id"]]),
            "change_history": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        base["knowledge"][record["id"]] = record
        self._save_json(self.knowledge_base_path, base)
        return copy.deepcopy(record)

    def _create_change_candidate(
        self,
        candidate: dict[str, Any],
        *,
        existing: dict[str, Any],
        proposed_by: str = "",
        save: bool = True,
    ) -> dict[str, Any]:
        normalized = self._normalize_candidate(candidate)
        before = self._knowledge_snapshot(existing)
        after = self._build_after_snapshot(existing, normalized)
        normalized.update(
            {
                "status": "pending_change",
                "change_type": "update_existing",
                "target_knowledge_id": existing["id"],
                "proposed_by": normalize_text(proposed_by) or normalize_text(normalized.get("owner")),
                "original_owner": existing.get("owner", ""),
                "before": before,
                "after": after,
                "change_summary": self._build_change_summary(before, after),
            }
        )
        if save:
            data = self._load_candidates()
            data["candidates"][normalized["id"]] = normalized
            self._save_json(self.candidates_path, data)
        return copy.deepcopy(normalized)

    def _apply_change_candidate(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        target_id = normalize_text(candidate.get("target_knowledge_id"))
        if not target_id:
            return None
        base = self._load_knowledge_base()
        record = base["knowledge"].get(target_id)
        if not record:
            return None

        before = self._knowledge_snapshot(record)
        after = candidate.get("after") if isinstance(candidate.get("after"), dict) else self._build_after_snapshot(record, candidate)
        original_owner = record.get("owner", "")
        record.setdefault("change_history", [])
        record["change_history"].append(
            {
                "version": int(record.get("version") or 1),
                "snapshot": before,
                "changed_by": normalize_text(candidate.get("proposed_by")) or normalize_text(candidate.get("owner")),
                "candidate_id": candidate.get("id", ""),
                "changed_at": now_iso(),
            }
        )
        record.update(
            {
                "kind": after.get("kind") or record.get("kind", "term"),
                "name": after.get("name") or record.get("name", ""),
                "canonical_definition": after.get("canonical_definition", record.get("canonical_definition", "")),
                "logic": after.get("logic", record.get("logic", "")),
                "examples": unique_values(after.get("examples", record.get("examples", []))),
                "paraphrases": unique_values(after.get("paraphrases", record.get("paraphrases", []))),
                "formula": after.get("formula", record.get("formula")),
                "conditions": unique_values(after.get("conditions", record.get("conditions", []))),
                "domain": after.get("domain", record.get("domain", "")),
                "owner": original_owner,
                "version": int(record.get("version") or 1) + 1,
                "status": "approved",
                "evidence_event_ids": unique_values(record.get("evidence_event_ids", []) + [candidate.get("source_event_id", "")]),
                "candidate_ids": unique_values(record.get("candidate_ids", []) + [candidate.get("id", "")]),
                "updated_at": now_iso(),
            }
        )
        base["knowledge"][target_id] = record
        self._save_json(self.knowledge_base_path, base)
        return copy.deepcopy(record)

    def _knowledge_snapshot(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": record.get("id", ""),
            "kind": record.get("kind", ""),
            "name": record.get("name", ""),
            "canonical_definition": record.get("canonical_definition", ""),
            "logic": record.get("logic", ""),
            "examples": unique_values(record.get("examples", [])),
            "paraphrases": unique_values(record.get("paraphrases", [])),
            "formula": record.get("formula"),
            "conditions": unique_values(record.get("conditions", [])),
            "domain": record.get("domain", ""),
            "owner": record.get("owner", ""),
            "version": int(record.get("version") or 1),
        }

    def _build_after_snapshot(self, existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": candidate.get("kind") or existing.get("kind", "term"),
            "name": candidate.get("name") or existing.get("name", ""),
            "canonical_definition": candidate.get("definition") or existing.get("canonical_definition", ""),
            "logic": normalize_text(candidate.get("logic")) or existing.get("logic", ""),
            "examples": unique_values(existing.get("examples", []) + candidate.get("examples", [])),
            "paraphrases": unique_values(existing.get("paraphrases", []) + candidate.get("paraphrases", [])),
            "formula": candidate.get("formula") or existing.get("formula"),
            "conditions": unique_values(existing.get("conditions", []) + candidate.get("conditions", [])),
            "domain": candidate.get("domain") or existing.get("domain", ""),
            "owner": existing.get("owner", ""),
        }

    def _build_change_summary(self, before: dict[str, Any], after: dict[str, Any]) -> str:
        changed_fields = [
            field
            for field in ["canonical_definition", "logic", "examples", "paraphrases", "formula", "conditions", "domain"]
            if before.get(field) != after.get(field)
        ]
        return "Không có thay đổi nội dung" if not changed_fields else "Thay đổi: " + ", ".join(changed_fields)

    def _normalize_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        canonical_name, name_aliases = canonicalize_name_and_aliases(candidate.get("name"))
        normalized = {
            "id": normalize_text(candidate.get("id")) or new_id("cand"),
            "source_event_id": normalize_text(candidate.get("source_event_id")),
            "kind": normalize_text(candidate.get("kind")) or "term",
            "name": canonical_name,
            "definition": normalize_text(candidate.get("definition")),
            "logic": normalize_text(candidate.get("logic")),
            "examples": unique_values(candidate.get("examples", [])),
            "paraphrases": unique_values(name_aliases + candidate.get("paraphrases", [])),
            "formula": normalize_text(candidate.get("formula")) or None,
            "conditions": unique_values(candidate.get("conditions", [])),
            "domain": normalize_text(candidate.get("domain")),
            "owner": normalize_text(candidate.get("owner")),
            "confidence": normalize_confidence(candidate.get("confidence"), default=0.0),
            "status": normalize_text(candidate.get("status")) or "pending_review",
            "conflict_with": normalize_text(candidate.get("conflict_with")),
            "created_at": normalize_text(candidate.get("created_at")) or now_iso(),
        }
        for key in ["change_type", "target_knowledge_id", "proposed_by", "original_owner", "change_summary"]:
            if candidate.get(key) is not None:
                normalized[key] = normalize_text(candidate.get(key))
        for key in ["before", "after"]:
            if isinstance(candidate.get(key), dict):
                normalized[key] = copy.deepcopy(candidate[key])
        if normalized["kind"] not in ALLOWED_KINDS:
            normalized["kind"] = "term"
        if normalized["status"] not in ALLOWED_CANDIDATE_STATUSES:
            normalized["status"] = "pending_review"
        if not normalized["name"]:
            raise ValueError("Candidate thiếu name")
        return normalized

    def _editable_candidate_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "kind",
            "name",
            "definition",
            "logic",
            "examples",
            "paraphrases",
            "formula",
            "conditions",
            "domain",
            "owner",
            "confidence",
        }
        return {key: value for key, value in updates.items() if key in allowed}

    def _find_knowledge_by_name(self, name: str) -> dict[str, Any] | None:
        normalized_name = normalize_lookup(name)
        if not normalized_name:
            return None
        for record in self._load_knowledge_base()["knowledge"].values():
            names = [record.get("name", ""), *record.get("paraphrases", [])]
            if normalized_name in {normalize_lookup(item) for item in names}:
                return copy.deepcopy(record)
        return None

    def _definitions_compatible(self, canonical: str, incoming: str) -> bool:
        canonical_norm = normalize_lookup(canonical)
        incoming_norm = normalize_lookup(incoming)
        if not canonical_norm or not incoming_norm:
            return True
        return canonical_norm == incoming_norm

    def _contains_term(self, text: str, term: str) -> bool:
        cleaned_term = normalize_text(term)
        if not cleaned_term:
            return False
        if ACRONYM_PATTERN.fullmatch(cleaned_term):
            pattern = rf"(?<![A-Z0-9]){re.escape(cleaned_term)}(?![A-Z0-9])"
            return bool(re.search(pattern, text.upper()))
        return normalize_lookup(cleaned_term) in normalize_lookup(text)

    def _normalize_data_dictionary(self, record: dict[str, Any]) -> dict[str, Any]:
        table = normalize_text(record.get("table"))
        if not table:
            raise ValueError("Data dictionary thiếu table")
        columns = []
        for column in record.get("columns", []):
            if not isinstance(column, dict):
                continue
            name = normalize_text(column.get("name"))
            if not name:
                continue
            columns.append(
                {
                    "name": name,
                    "business_meaning": normalize_text(column.get("business_meaning")),
                    "data_type": normalize_text(column.get("data_type")),
                    "aliases": unique_values(column.get("aliases", [])),
                }
            )
        relationships = []
        for relationship in record.get("relationships", []):
            if not isinstance(relationship, dict):
                continue
            relationships.append(
                {
                    "from": normalize_text(relationship.get("from")),
                    "to": normalize_text(relationship.get("to")),
                    "type": normalize_text(relationship.get("type")),
                }
            )
        return {
            "id": normalize_text(record.get("id")) or new_id("dict"),
            "table": table,
            "description": normalize_text(record.get("description")),
            "columns": columns,
            "relationships": relationships,
            "owner": normalize_text(record.get("owner")),
            "status": normalize_text(record.get("status")) or "approved",
            "created_at": normalize_text(record.get("created_at")) or now_iso(),
            "updated_at": normalize_text(record.get("updated_at")) or now_iso(),
        }

    def _normalize_question_example(self, example: dict[str, Any]) -> dict[str, Any]:
        question = normalize_text(example.get("question"))
        sql = normalize_text(example.get("sql"))
        if not question:
            raise ValueError("Question example thiếu question")
        if not sql:
            raise ValueError("Question example thiếu sql")
        return {
            "id": normalize_text(example.get("id")) or new_id("qex"),
            "question": question,
            "sql": sql,
            "explanation": normalize_text(example.get("explanation")),
            "concepts": unique_values(example.get("concepts", [])),
            "used_tables": unique_values(example.get("used_tables", [])),
            "owner": normalize_text(example.get("owner")),
            "status": normalize_text(example.get("status")) or "approved",
            "created_at": normalize_text(example.get("created_at")) or now_iso(),
            "updated_at": normalize_text(example.get("updated_at")) or now_iso(),
        }

    def _dictionary_haystack(self, record: dict[str, Any]) -> str:
        parts = [record.get("table", ""), record.get("description", ""), record.get("owner", "")]
        for column in record.get("columns", []):
            parts.extend(
                [
                    column.get("name", ""),
                    column.get("business_meaning", ""),
                    column.get("data_type", ""),
                    " ".join(column.get("aliases", [])),
                ]
            )
        for relationship in record.get("relationships", []):
            parts.extend([relationship.get("from", ""), relationship.get("to", ""), relationship.get("type", "")])
        return " ".join(parts)

    def _dictionary_matches_term(self, record: dict[str, Any], term: str) -> bool:
        cleaned = normalize_text(term)
        if not cleaned:
            return False
        return self._contains_term(self._dictionary_haystack(record), cleaned)

    def _extract_question_terms(self, text: str) -> list[str]:
        cleaned = normalize_text(text)
        terms = extract_acronyms(cleaned)
        for match in re.finditer(r"(?:theo|by|group by|phân theo)\s+([A-Za-zÀ-ỹ_][\wÀ-ỹ_ ]{1,40})", cleaned, flags=re.IGNORECASE):
            terms.append(match.group(1).strip(" ?.,"))
        words = re.findall(r"[A-Za-zÀ-ỹ_][\wÀ-ỹ_]{2,}", cleaned)
        stopwords = {
            "bao",
            "nhiêu",
            "theo",
            "tháng",
            "ngày",
            "tuần",
            "quý",
            "năm",
            "cho",
            "của",
            "với",
            "trong",
            "là",
            "what",
            "how",
            "many",
            "much",
            "the",
            "per",
        }
        for word in words:
            if normalize_lookup(word) not in stopwords:
                terms.append(word)
        return unique_values(terms)

    def _build_missing_dictionary_items(
        self,
        question: str,
        known: list[dict[str, Any]],
        detected_concepts: list[str],
    ) -> list[dict[str, str]]:
        business_terms = [item.get("name", "") for item in known] or detected_concepts or [question]
        missing = [
            {
                "type": "table_mapping",
                "concept": term,
                "question": f"{term} lấy từ bảng nào?",
            }
            for term in unique_values(business_terms)
        ]
        for concept in detected_concepts:
            if concept not in business_terms:
                missing.append(
                    {
                        "type": "column_mapping",
                        "concept": concept,
                        "question": f"{concept} nằm ở bảng/cột nào?",
                    }
                )
        return missing

    def _build_sql_explanation(
        self,
        known: list[dict[str, Any]],
        dictionary: list[dict[str, Any]],
        example: dict[str, Any],
    ) -> list[str]:
        explanation = []
        explanation.extend(
            f"{item.get('name')}: lấy từ Domain Knowledge {item.get('id')}"
            for item in known
        )
        explanation.extend(
            f"{item.get('table')}: lấy từ Data Dictionary {item.get('id')}"
            for item in dictionary
        )
        if example.get("explanation"):
            explanation.append(example["explanation"])
        else:
            explanation.append(f"SQL draft lấy từ Question Example {example.get('id')}")
        return explanation

    def _load_candidates(self) -> dict[str, Any]:
        if self.db:
            return self.db.load_candidates()
        return self._load_json(self.candidates_path, empty_candidates)

    def _load_knowledge_base(self) -> dict[str, Any]:
        if self.db:
            return self.db.load_knowledge_base()
        return self._load_json(self.knowledge_base_path, empty_knowledge_base)

    def _load_teaching_sessions(self) -> dict[str, Any]:
        if self.db:
            return self.db.load_teaching_sessions()
        return self._load_json(self.teaching_sessions_path, empty_teaching_sessions)

    def _load_data_dictionary(self) -> dict[str, Any]:
        if self.db:
            return self.db.load_data_dictionary()
        return self._load_json(self.data_dictionary_path, empty_data_dictionary)

    def _load_question_examples(self) -> dict[str, Any]:
        if self.db:
            return self.db.load_question_examples()
        return self._load_json(self.question_examples_path, empty_question_examples)

    def _load_json(self, path: Path, default_factory) -> dict[str, Any]:
        self.bootstrap_minimal(path, default_factory)
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data

    def _save_json(self, path: Path, data: dict[str, Any]) -> None:
        if self.db:
            if path == self.candidates_path:
                self.db.save_candidates(data)
                return
            if path == self.knowledge_base_path:
                self.db.save_knowledge_base(data)
                return
            if path == self.teaching_sessions_path:
                self.db.save_teaching_sessions(data)
                return
            if path == self.data_dictionary_path:
                self.db.save_data_dictionary(data)
                return
            if path == self.question_examples_path:
                self.db.save_question_examples(data)
                return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False, sort_keys=True)
            file.write("\n")

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            file.write("\n")

    def bootstrap_minimal(self, path: Path, default_factory) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._save_json(path, default_factory())
