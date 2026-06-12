import copy
import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib import error

from agent_core.constants import (
    ACRONYM_PATTERN,
    ALLOWED_CANDIDATE_STATUSES,
    ALLOWED_KINDS,
    ALLOWED_TEACHING_SESSION_STATUSES,
    CANDIDATES_PATH,
    CHAT_SESSIONS_PATH,
    DATA_DICTIONARY_PATH,
    DATA_DIR,
    DOCUMENT_CHUNKS_PATH,
    KNOWLEDGE_BASE_PATH,
    QUESTION_EXAMPLES_PATH,
    RAW_EVENTS_PATH,
    TEACHING_SESSIONS_PATH,
)
from agent_core.llm import AgentLLMClient
from agent_core.memory import AgentBaseMemoryEventStore, LocalChatSessionEventStore, MemoryClient, SessionContextStoreError
from agent_core.parser import KnowledgeParser
from agent_core.runtime_skills import RuntimeSkillRegistry
from agent_core.storage import PostgresStorage
from agent_core.utils import (
    candidate_template,
    canonicalize_name_and_aliases,
    chunk_text,
    empty_candidates,
    empty_chat_sessions,
    empty_data_dictionary,
    empty_knowledge_base,
    empty_question_examples,
    empty_teaching_sessions,
    extract_acronyms,
    new_id,
    normalize_confidence,
    normalize_lookup,
    normalize_text,
    now_iso,
    parse_bool_flag,
    split_sentences,
    unique_values,
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
        chat_sessions_path: Path | str = CHAT_SESSIONS_PATH,
        data_dictionary_path: Path | str = DATA_DICTIONARY_PATH,
        question_examples_path: Path | str = QUESTION_EXAMPLES_PATH,
        database_url: str | None = None,
        parser: KnowledgeParser | None = None,
        llm_client: Any | None = None,
        chat_context_backend: str | None = None,
        chat_context_memory_id: str | None = None,
        chat_context_event_limit: int | None = None,
        chat_context_fallback_on_error: bool | None = None,
        runtime_skills_enabled: bool | None = None,
        chat_memory_timeout_ms: int | None = None,
        chat_history_turn_limit: int | None = None,
        chat_memory_hydrate_when_empty: bool | None = None,
    ) -> None:
        self.raw_events_path = Path(raw_events_path)
        self.candidates_path = Path(candidates_path)
        self.knowledge_base_path = Path(knowledge_base_path)
        self.document_chunks_path = Path(document_chunks_path)
        self.teaching_sessions_path = Path(teaching_sessions_path)
        self.chat_sessions_path = Path(chat_sessions_path)
        self.data_dictionary_path = Path(data_dictionary_path)
        self.question_examples_path = Path(question_examples_path)
        self.database_url = normalize_text(database_url if database_url is not None else os.getenv("DATABASE_URL"))
        self.db = PostgresStorage(self.database_url) if self.database_url else None
        self.parser = parser or KnowledgeParser()
        self.llm_client = llm_client or AgentLLMClient()
        self.chat_context_backend = normalize_lookup(chat_context_backend if chat_context_backend is not None else os.getenv("CHAT_CONTEXT_BACKEND") or "auto")
        if self.chat_context_backend not in {"agentbase", "local", "auto"}:
            self.chat_context_backend = "auto"
        self.chat_context_memory_id = normalize_text(
            chat_context_memory_id if chat_context_memory_id is not None else os.getenv("CHAT_CONTEXT_MEMORY_ID")
        )
        self.chat_context_event_limit = chat_context_event_limit or int(os.getenv("CHAT_CONTEXT_EVENT_LIMIT") or "12")
        fallback_env = os.getenv("CHAT_CONTEXT_FALLBACK_ON_MEMORY_ERROR")
        self.chat_context_fallback_on_error = (
            chat_context_fallback_on_error
            if chat_context_fallback_on_error is not None
            else normalize_lookup(fallback_env or "true") not in {"0", "false", "no"}
        )
        self.runtime_skills_enabled = parse_bool_flag(
            runtime_skills_enabled if runtime_skills_enabled is not None else os.getenv("CHAT_RUNTIME_SKILLS_ENABLED"),
            default=True,
        )
        self.chat_memory_timeout_ms = chat_memory_timeout_ms or int(os.getenv("CHAT_MEMORY_TIMEOUT_MS") or "1500")
        self.chat_history_turn_limit = chat_history_turn_limit or int(os.getenv("CHAT_HISTORY_TURN_LIMIT") or "12")
        self.chat_memory_hydrate_when_empty = parse_bool_flag(
            chat_memory_hydrate_when_empty
            if chat_memory_hydrate_when_empty is not None
            else os.getenv("CHAT_MEMORY_HYDRATE_WHEN_EMPTY"),
            default=True,
        )

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
        if not self.chat_sessions_path.exists():
            self._save_json(self.chat_sessions_path, empty_chat_sessions())
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
            "chat_context_backend": self.chat_context_backend,
            "chat_context_memory_configured": bool(self.chat_context_memory_id),
            "chat_context_event_limit": self.chat_context_event_limit,
            "chat_context_fallback_on_memory_error": self.chat_context_fallback_on_error,
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
            normalized_haystack = normalize_lookup(haystack)
            if not normalized_query or normalized_query in normalized_haystack:
                item = copy.deepcopy(example)
                item["_match_score"] = 100 if normalized_query else 0
                matches.append(item)
                continue
            example_terms = {normalize_lookup(term) for term in self._extract_question_terms(haystack)}
            overlap = [term for term in query_terms if normalize_lookup(term) in example_terms]
            if overlap:
                item = copy.deepcopy(example)
                item["_match_score"] = len(overlap)
                matches.append(item)
        return sorted(matches, key=lambda item: (int(item.get("_match_score") or 0), item.get("updated_at", "")), reverse=True)

    def _filter_question_examples_for_known_concepts(
        self,
        examples: list[dict[str, Any]],
        known: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not known:
            return examples
        concept_terms: list[str] = []
        for item in known:
            concept_terms.extend([item.get("name", ""), *item.get("paraphrases", [])])
        normalized_terms = [normalize_lookup(term) for term in concept_terms if normalize_lookup(term)]
        if not normalized_terms:
            return examples

        filtered = []
        for example in examples:
            haystack = normalize_lookup(
                " ".join(
                    [
                        example.get("question", ""),
                        example.get("explanation", ""),
                        example.get("sql", ""),
                        " ".join(example.get("concepts", [])),
                        " ".join(example.get("used_tables", [])),
                    ]
                )
            )
            if any(self._contains_term(haystack, term) for term in normalized_terms):
                filtered.append(example)
        return filtered

    def chat(
        self,
        *,
        message: str,
        user_id: str = "",
        session_id: str = "",
        pending_action_id: str = "",
        debug_context: bool = False,
        use_runtime_skills: bool | None = None,
    ) -> dict[str, Any]:
        total_started = time.perf_counter()
        latency: dict[str, float] = {}
        cleaned = normalize_text(message)
        if not cleaned:
            raise ValueError("Thiếu message")

        chat_session = self._get_or_create_chat_session(session_id=session_id, user_id=user_id)
        had_local_messages = bool(chat_session.get("messages"))
        chat_session["_debug_context"] = bool(debug_context)
        chat_session["_use_runtime_skills"] = parse_bool_flag(use_runtime_skills, default=self.runtime_skills_enabled)
        chat_session["_latency_ms"] = latency
        chat_session["_chat_started_at"] = total_started
        chat_session["_memory_hydrate_needed"] = not had_local_messages
        self._append_chat_message(chat_session, role="user", content=cleaned)
        effective_user_id = normalize_text(user_id) or chat_session.get("user_id", "")
        effective_session_id = chat_session["id"]
        chat_session["_context_user_id"] = effective_user_id
        chat_session["_context_session_id"] = effective_session_id

        confirmation_result = self._handle_chat_confirmation(
            chat_session=chat_session,
            message=cleaned,
            pending_action_id=pending_action_id,
        )
        if confirmation_result:
            self._record_chat_total_latency(chat_session)
            self._save_chat_session(chat_session)
            return confirmation_result

        pending_status_result = self._handle_pending_status_query(chat_session=chat_session, message=cleaned)
        if pending_status_result:
            self._record_chat_total_latency(chat_session)
            self._save_chat_session(chat_session)
            return pending_status_result

        refinement_result = self._handle_pending_action_refinement(
            chat_session=chat_session,
            message=cleaned,
        )
        if refinement_result:
            self._record_chat_total_latency(chat_session)
            self._save_chat_session(chat_session)
            return refinement_result

        active_runtime_cancel_result = self._handle_active_runtime_skill_cancel(chat_session=chat_session, message=cleaned)
        if active_runtime_cancel_result:
            self._record_chat_total_latency(chat_session)
            self._save_chat_session(chat_session)
            return active_runtime_cancel_result

        memory_started = time.perf_counter()
        conversation_context = self._build_conversation_context(
            chat_session=chat_session,
            message=cleaned,
            user_id=effective_user_id,
            session_id=effective_session_id,
        )
        latency["memory"] = self._elapsed_ms(memory_started)
        chat_session["_conversation_context"] = conversation_context

        retrieval_started = time.perf_counter()
        context = self._build_chat_context(cleaned, conversation_context=conversation_context)
        context["_runtime_skills_enabled"] = bool(chat_session.get("_use_runtime_skills", self.runtime_skills_enabled))
        latency["retrieval"] = self._elapsed_ms(retrieval_started)
        if not self._llm_configured():
            result = self._llm_required_chat_response(chat_session=chat_session, message=cleaned)
            self._record_chat_total_latency(chat_session)
            self._save_chat_session(chat_session)
            return result

        plan = self._plan_chat_action(
            chat_session=chat_session,
            raw_message=cleaned,
            context=context,
            conversation_context=conversation_context,
        )
        execute_started = time.perf_counter()
        result = self._execute_planned_chat_action(
            chat_session=chat_session,
            raw_message=cleaned,
            context=context,
            conversation_context=conversation_context,
            plan=plan,
        )
        latency["execute"] = self._elapsed_ms(execute_started)
        self._record_chat_total_latency(chat_session)
        self._save_chat_session(chat_session)
        return result

    def ask_data_question(self, question: str) -> dict[str, Any]:
        cleaned = normalize_text(question)
        if not cleaned:
            raise ValueError("Thiếu câu hỏi nghiệp vụ")

        analysis = self.analyze_text(cleaned)
        known = analysis["known"]
        detected_concepts = unique_values([*analysis["detected_terms"], *self._extract_question_terms(cleaned)])
        missing_knowledge = analysis["unknown"]
        dictionary_matches = self._search_dictionary_for_question(cleaned, known)
        example_matches = self._filter_question_examples_for_known_concepts(self.search_question_examples(cleaned), known)

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

        missing_dictionary = self._build_missing_dictionary_items(cleaned, known, detected_concepts, dictionary_matches)
        if missing_dictionary:
            return {
                "status": "needs_dictionary",
                "question": cleaned,
                "detected_concepts": detected_concepts,
                "known_knowledge": known,
                "missing": missing_dictionary,
                "dictionary": dictionary_matches,
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

        llm_sql = self._build_llm_sql_draft(cleaned, known, dictionary_matches)
        if llm_sql:
            return {
                "status": "sql_draft",
                "question": cleaned,
                "detected_concepts": detected_concepts,
                "sql": llm_sql["sql"],
                "explanation": llm_sql.get("explanation", []),
                "used_knowledge_ids": [item["id"] for item in known],
                "used_dictionary_ids": [item["id"] for item in dictionary_matches],
                "used_example_ids": [],
                "knowledge": known,
                "dictionary": dictionary_matches,
                "examples": [],
                "answer": llm_sql.get("answer") or "Tôi đã tạo SQL draft từ context retrieved.",
            }

        sql = self._build_deterministic_sql_draft(cleaned, known, dictionary_matches, detected_concepts)
        if sql:
            return {
                "status": "sql_draft",
                "question": cleaned,
                "detected_concepts": detected_concepts,
                "sql": sql,
                "explanation": self._build_sql_explanation(known, dictionary_matches, {}),
                "used_knowledge_ids": [item["id"] for item in known],
                "used_dictionary_ids": [item["id"] for item in dictionary_matches],
                "used_example_ids": [],
                "knowledge": known,
                "dictionary": dictionary_matches,
                "examples": [],
                "answer": "Tôi đã tạo SQL draft từ Domain Knowledge và Data Dictionary đã approved.",
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

    def _llm_configured(self) -> bool:
        configured = getattr(self.llm_client, "configured", None)
        return bool(configured()) if callable(configured) else False

    def _build_chat_context(self, message: str, conversation_context: dict[str, Any] | None = None) -> dict[str, Any]:
        knowledge = self._search_knowledge_for_chat(message)
        dictionary = self._search_dictionary_for_chat(message, knowledge)
        if not dictionary:
            dictionary = self.search_data_dictionary(message)[:5]
        return {
            "knowledge": knowledge[:6],
            "dictionary": dictionary[:6],
            "examples": self.search_question_examples(message)[:5],
            "conversation_context": conversation_context or {},
        }

    def _llm_required_chat_response(self, *, chat_session: dict[str, Any], message: str) -> dict[str, Any]:
        response = {
            "status": "llm_required",
            "intent": "llm_required",
            "answer": (
                "Chat tự nhiên hiện yêu cầu LLM planner. Bạn cần cấu hình LLM_API_KEY, "
                "LLM_BASE_URL và LLM_MODEL để agent có thể tự hiểu ngữ cảnh và route câu trả lời."
            ),
            "question": message,
            "missing": [
                {
                    "type": "llm_config",
                    "concept": "chat_planner",
                    "question": "Cần cấu hình LLM để dùng chat tự nhiên.",
                }
            ],
            "used_knowledge_ids": [],
            "used_dictionary_ids": [],
            "used_example_ids": [],
            "debug": {
                "llm_used": False,
                "fallback_used": False,
                "planner_used": False,
                "planner_fallback_reason": "llm_not_configured",
            },
        }
        return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)

    def _plan_chat_action(
        self,
        *,
        chat_session: dict[str, Any],
        raw_message: str,
        context: dict[str, Any],
        conversation_context: dict[str, Any],
    ) -> dict[str, Any]:
        compact_input = self._build_chat_planner_input(
            chat_session=chat_session,
            raw_message=raw_message,
            context=context,
            conversation_context=conversation_context,
        )
        system = (
            "You are the LLM action planner for a Vietnamese business data agent. "
            "Return only JSON. Choose the next assistant action naturally from the user's message and context. "
            "Allowed actions: answer_direct, ask_clarification, propose_teaching, propose_append_teaching, "
            "propose_commit_teaching, propose_data_query, answer_and_propose_data_query, refine_pending_action, recall_conversation, noop. "
            "Pure definition/help/recall can be answered directly. Teaching, appending, committing, SQL/data query, "
            "or any KB/data side effect must require confirmation and must be proposed as a pending action. "
            "Use only retrieved knowledge/dictionary/examples. Do not invent metric definitions, tables, columns, or SQL. "
            "If runtime_skills are present in the input, follow those instructions as domain-specific behavior rules. "
            "For data questions, propose a data query; Python will run guarded data flow only after user confirmation. "
            "If the user message is a short follow-up and a pending action is relevant, refine that pending action instead of treating the message as a new standalone question. "
            "Output fields: action, answer, requires_confirmation, pending_action_type, payload, clarifying_questions, "
            "confidence, used_context_terms, reasoning_summary."
        )
        planner_started = time.perf_counter()
        parsed = self.llm_client.complete_json(
            system=system,
            user=json.dumps(compact_input, ensure_ascii=False),
            temperature=0,
        )
        self._record_chat_latency(chat_session, "planner", planner_started)
        if not isinstance(parsed, dict):
            parsed = {}
        allowed = {
            "answer_direct",
            "ask_clarification",
            "propose_teaching",
            "propose_append_teaching",
            "propose_commit_teaching",
            "propose_data_query",
            "answer_and_propose_data_query",
            "refine_pending_action",
            "recall_conversation",
            "noop",
        }
        action = normalize_lookup(parsed.get("action"))
        if action not in allowed:
            parsed = {
                "action": "ask_clarification",
                "answer": "Mình chưa chắc nên xử lý câu này theo hướng nào. Bạn muốn hỏi định nghĩa, dạy knowledge, hay chuẩn bị query data?",
                "requires_confirmation": False,
                "confidence": 0,
                "planner_fallback_reason": "invalid_planner_action",
            }
        parsed["action"] = normalize_lookup(parsed.get("action")) or "ask_clarification"
        if not isinstance(parsed.get("payload"), dict):
            parsed["payload"] = {}
        if not isinstance(parsed.get("clarifying_questions"), list):
            parsed["clarifying_questions"] = []
        if not isinstance(parsed.get("used_context_terms"), list):
            parsed["used_context_terms"] = []
        parsed["_runtime_skills_used"] = [item.get("name", "") for item in compact_input.get("runtime_skills", []) if item.get("name")]
        parsed["_runtime_skill_candidates"] = compact_input.get("runtime_skill_candidates", [])
        parsed["_runtime_skill_selection_reason"] = compact_input.get("runtime_skill_selection_reason", "")
        parsed["_active_runtime_skill"] = normalize_text(compact_input.get("active_runtime_skill"))
        parsed["_runtime_skills_enabled"] = bool(context.get("_runtime_skills_enabled", True))
        return parsed

    def _build_chat_planner_input(
        self,
        *,
        chat_session: dict[str, Any],
        raw_message: str,
        context: dict[str, Any],
        conversation_context: dict[str, Any],
    ) -> dict[str, Any]:
        skill_started = time.perf_counter()
        context["_active_runtime_skill"] = normalize_text(chat_session.get("active_runtime_skill"))
        runtime_skills = self._runtime_chat_skills(raw_message=raw_message, context=context)
        if context.get("_clear_active_runtime_skill"):
            chat_session["active_runtime_skill"] = ""
        elif context.get("_next_active_runtime_skill"):
            chat_session["active_runtime_skill"] = normalize_text(context.get("_next_active_runtime_skill"))
        self._record_chat_latency(chat_session, "skill_select", skill_started)
        runtime_skill_candidates = context.get("_runtime_skill_candidates", [])
        runtime_skill_selection_reason = context.get("_runtime_skill_selection_reason", "")
        pending_actions = [
            self._pending_action_planner_summary(action)
            for action in self._pending_chat_actions(chat_session)
        ]
        active_teaching = {}
        teaching_session_id = chat_session.get("active_teaching_session_id", "")
        if teaching_session_id:
            try:
                teaching = self.summarize_teach_session(session_id=teaching_session_id)
                active_teaching = {
                    "session_id": teaching_session_id,
                    "status": teaching.get("status"),
                    "summary": teaching.get("summary", {}),
                    "draft": teaching.get("draft", {}),
                }
            except ValueError:
                active_teaching = {"session_id": teaching_session_id, "status": "missing"}
        return {
            "raw_message": raw_message,
            "conversation_history": conversation_context.get("conversation_history", []),
            "memory": {
                "backend": conversation_context.get("backend"),
                "hydrated": conversation_context.get("memory_hydrated", False),
                "sync_status": conversation_context.get("memory_sync_status", ""),
                "timeout": conversation_context.get("memory_timeout", False),
                "context_terms": conversation_context.get("context_terms", []),
            },
            "active_teaching": active_teaching,
            "pending_actions": pending_actions,
            "retrieved": {
                "knowledge": [self._compact_planner_knowledge(item) for item in context.get("knowledge", [])],
                "dictionary": [self._compact_planner_dictionary(item) for item in context.get("dictionary", [])],
                "examples": [self._compact_planner_example(item) for item in context.get("examples", [])],
            },
            "runtime_skill_candidates": runtime_skill_candidates,
            "runtime_skill_selection_reason": runtime_skill_selection_reason,
            "active_runtime_skill": normalize_text(chat_session.get("active_runtime_skill")),
            "runtime_skills": runtime_skills,
            "safety_policy": {
                "no_confirmation_needed": ["answer_direct", "ask_clarification", "recall_conversation"],
                "confirmation_required": [
                    "propose_teaching",
                    "propose_append_teaching",
                    "propose_commit_teaching",
                    "propose_data_query",
                    "answer_and_propose_data_query",
                    "refine_pending_action",
                ],
                "data_rule": "Never draft SQL or query data before user confirms the pending data_query action.",
            },
        }

    def _runtime_chat_skills(self, *, raw_message: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        if context.get("_runtime_skills_enabled") is False:
            context["_runtime_skill_candidates"] = []
            context["_runtime_skill_selection_reason"] = "runtime skills disabled by request/config"
            context["_runtime_skills_selected_names"] = []
            return []
        registry = RuntimeSkillRegistry()
        active_skill_name = normalize_text(context.get("_active_runtime_skill"))
        if active_skill_name:
            active_skill = self._runtime_skill_by_name(registry, active_skill_name)
            runtime = active_skill.get("runtime", {}) if isinstance(active_skill.get("runtime"), dict) else {}
            if active_skill and runtime.get("sticky") is True:
                card = registry.skill_card(active_skill)
                card["score"] = max(int(card.get("score") or 0), 100)
                card["matched_by"] = "active_session"
                context["_runtime_skill_candidates"] = [card]
                context["_runtime_skill_selection_reason"] = f"using active runtime skill from session: {active_skill_name}"
                context["_runtime_skills_selected_names"] = [active_skill_name]
                context["_next_active_runtime_skill"] = active_skill_name
                return [registry.skill_payload(active_skill)]
            context["_clear_active_runtime_skill"] = True
        skill_query = self._runtime_skill_query(raw_message=raw_message, context=context)
        candidates = registry.query_candidates(skill_query)
        cards = [registry.skill_card(skill) for skill in candidates]
        selected_names, reason = self._auto_select_runtime_skill_names(cards)
        if not selected_names and cards:
            selected_names, reason = self._select_runtime_skill_names(raw_message=raw_message, context=context, skill_cards=cards)
        selected_skills = [skill for skill in candidates if skill.get("name") in selected_names]
        sticky_selected = next(
            (
                skill
                for skill in selected_skills
                if isinstance(skill.get("runtime"), dict) and skill.get("runtime", {}).get("sticky") is True
            ),
            None,
        )
        if sticky_selected:
            context["_next_active_runtime_skill"] = normalize_text(sticky_selected.get("name"))
        context["_runtime_skill_candidates"] = cards
        context["_runtime_skill_selection_reason"] = reason
        context["_runtime_skills_selected_names"] = selected_names
        return [registry.skill_payload(skill) for skill in selected_skills]

    def _runtime_skill_by_name(self, registry: RuntimeSkillRegistry, name: str) -> dict[str, Any]:
        for skill in registry.enabled_skills():
            if normalize_text(skill.get("name")) == name:
                return skill
        return {}

    def _auto_select_runtime_skill_names(self, skill_cards: list[dict[str, Any]]) -> tuple[list[str], str]:
        if len(skill_cards) != 1:
            return [], ""
        card = skill_cards[0]
        name = normalize_text(card.get("name"))
        try:
            score = int(card.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        if name == "air-sql-analyst" and score >= 20:
            return [name], "auto-selected high-score runtime skill candidate"
        return [], ""

    def _runtime_skill_query(self, *, raw_message: str, context: dict[str, Any]) -> str:
        parts = [
            raw_message,
            *[item.get("domain", "") for item in context.get("knowledge", [])],
            *[item.get("name", "") for item in context.get("knowledge", [])],
            *[item.get("table", "") for item in context.get("dictionary", [])],
            *[" ".join(column.get("name", "") for column in item.get("columns", [])) for item in context.get("dictionary", [])],
            *[" ".join(item.get("used_tables", [])) for item in context.get("examples", [])],
            *[" ".join(item.get("concepts", [])) for item in context.get("examples", [])],
        ]
        return normalize_text(" ".join(parts))

    def _select_runtime_skill_names(
        self,
        *,
        raw_message: str,
        context: dict[str, Any],
        skill_cards: list[dict[str, Any]],
    ) -> tuple[list[str], str]:
        if not skill_cards:
            return [], ""
        parsed = self.llm_client.complete_json(
            system=(
                "You select runtime skills for a business-data chat planner. Return only JSON with "
                "selected_skills as an array of skill names from the candidates, and reason as a short string. "
                "Select a skill only if its description is relevant to the user message and retrieved context."
            ),
            user=json.dumps(
                {
                    "message": raw_message,
                    "retrieved": {
                        "knowledge_names": [item.get("name", "") for item in context.get("knowledge", [])],
                        "knowledge_domains": [item.get("domain", "") for item in context.get("knowledge", [])],
                        "dictionary_tables": [item.get("table", "") for item in context.get("dictionary", [])],
                        "example_tables": [table for item in context.get("examples", []) for table in item.get("used_tables", [])],
                        "example_concepts": [concept for item in context.get("examples", []) for concept in item.get("concepts", [])],
                    },
                    "candidates": skill_cards,
                },
                ensure_ascii=False,
            ),
            temperature=0,
        )
        valid_names = {card.get("name", "") for card in skill_cards}
        selected = parsed.get("selected_skills") if isinstance(parsed, dict) else []
        if not isinstance(selected, list):
            selected = []
        selected_names = unique_values([str(item) for item in selected if str(item) in valid_names])
        reason = normalize_text(parsed.get("reason")) if isinstance(parsed, dict) else ""
        return selected_names, reason

    def _execute_planned_chat_action(
        self,
        *,
        chat_session: dict[str, Any],
        raw_message: str,
        context: dict[str, Any],
        conversation_context: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        action = normalize_lookup(plan.get("action"))
        payload = plan.get("payload", {}) if isinstance(plan.get("payload"), dict) else {}
        planner_answer = normalize_text(plan.get("answer"))
        debug = self._planner_debug(plan)

        if action == "answer_direct":
            response = {
                "status": "answered",
                "intent": "planner_answer",
                "answer": planner_answer or "Mình chưa có câu trả lời đủ rõ từ context hiện tại.",
                "question": raw_message,
                "missing": [],
                "used_knowledge_ids": [item["id"] for item in context.get("knowledge", [])],
                "used_dictionary_ids": [item["id"] for item in context.get("dictionary", [])],
                "used_example_ids": [item["id"] for item in context.get("examples", [])],
                "debug": debug,
            }
            self._attach_debug_context(response, context=context, chat_session=chat_session)
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)

        if action == "recall_conversation":
            response = {
                "status": "answered",
                "intent": "conversation_recall",
                "answer": planner_answer or "Mình chưa thấy đủ lịch sử trong session này để trả lời chắc chắn.",
                "question": raw_message,
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": debug,
            }
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)

        if action == "ask_clarification" or action == "noop":
            questions = [normalize_text(item) for item in plan.get("clarifying_questions", []) if normalize_text(item)]
            answer = planner_answer or (questions[0] if questions else "Bạn nói rõ hơn một chút để mình xử lý đúng hướng nhé.")
            response = {
                "status": "needs_clarification",
                "intent": "clarification",
                "answer": answer,
                "question": raw_message,
                "missing": [
                    {
                        "type": "clarification",
                        "concept": raw_message,
                        "question": question,
                    }
                    for question in (questions or [answer])
                ],
                "used_knowledge_ids": [item["id"] for item in context.get("knowledge", [])],
                "used_dictionary_ids": [item["id"] for item in context.get("dictionary", [])],
                "used_example_ids": [item["id"] for item in context.get("examples", [])],
                "debug": debug,
            }
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)

        if action == "refine_pending_action":
            pending_action_id = normalize_text(payload.get("pending_action_id"))
            refinement = normalize_text(payload.get("refined_message") or payload.get("message")) or raw_message
            return self._refine_pending_data_query_action(
                chat_session=chat_session,
                message=refinement,
                pending_action_id=pending_action_id,
                planner_answer=planner_answer,
                planner_debug=debug,
            )

        if action == "propose_data_query":
            return self._propose_data_query_action(
                chat_session=chat_session,
                message=normalize_text(payload.get("resolved_message")) or raw_message,
                raw_message=raw_message,
                context=context,
                conversation_context=conversation_context,
                llm_used=True,
                planner_answer=planner_answer,
                planner_debug=debug,
            )

        if action == "answer_and_propose_data_query":
            return self._propose_data_query_action(
                chat_session=chat_session,
                message=normalize_text(payload.get("resolved_message")) or raw_message,
                raw_message=raw_message,
                context=context,
                conversation_context=conversation_context,
                llm_used=True,
                planner_answer=planner_answer,
                planner_debug=debug,
            )

        if action == "propose_teaching":
            return self._propose_teaching_action(
                chat_session=chat_session,
                message=normalize_text(payload.get("message")) or raw_message,
                llm_used=True,
                planner_answer=planner_answer,
                planner_debug=debug,
            )

        if action == "propose_append_teaching":
            if not chat_session.get("active_teaching_session_id"):
                response = {
                    "status": "needs_clarification",
                    "intent": "clarification",
                    "answer": planner_answer or "Mình chưa thấy draft teaching nào đang active để append. Bạn muốn bắt đầu teaching session mới không?",
                    "question": raw_message,
                    "missing": [],
                    "used_knowledge_ids": [],
                    "used_dictionary_ids": [],
                    "used_example_ids": [],
                    "debug": {**debug, "planner_fallback_reason": "append_without_active_teaching"},
                }
                return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)
            return self._propose_append_teaching_action(
                chat_session=chat_session,
                message=normalize_text(payload.get("message")) or raw_message,
                llm_used=True,
                planner_answer=planner_answer,
                planner_debug=debug,
            )

        if action == "propose_commit_teaching":
            teaching_session_id = chat_session.get("active_teaching_session_id", "")
            if not teaching_session_id:
                response = {
                    "status": "needs_clarification",
                    "intent": "clarification",
                    "answer": planner_answer or "Mình chưa thấy draft teaching nào đang active để commit.",
                    "question": raw_message,
                    "missing": [],
                    "used_knowledge_ids": [],
                    "used_dictionary_ids": [],
                    "used_example_ids": [],
                    "debug": {**debug, "planner_fallback_reason": "commit_without_active_teaching"},
                }
                return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)
            action_record = self._create_commit_teaching_action(chat_session, teaching_session_id=teaching_session_id)
            response = {
                "status": "needs_confirmation",
                "intent": "teach_knowledge",
                "answer": planner_answer or "Bạn confirm mình ghi draft teaching này vào KB chứ?",
                "question": raw_message,
                "missing": [
                    {
                        "type": "confirmation",
                        "concept": "commit_teaching",
                        "question": "Bạn confirm ghi draft teaching này vào KB chứ?",
                    }
                ],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": debug,
            }
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=True, pending_action=action_record)

        response = {
            "status": "needs_clarification",
            "intent": "clarification",
            "answer": "Planner chưa trả về action hợp lệ. Bạn diễn đạt lại giúp mình nhé.",
            "question": raw_message,
            "missing": [],
            "used_knowledge_ids": [],
            "used_dictionary_ids": [],
            "used_example_ids": [],
            "debug": {**debug, "planner_fallback_reason": "unhandled_action"},
        }
        return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)

    def _planner_debug(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "llm_used": True,
            "fallback_used": False,
            "planner_used": True,
            "planner_action": normalize_lookup(plan.get("action")),
            "planner_confidence": plan.get("confidence", 0),
            "planner_fallback_reason": plan.get("planner_fallback_reason", ""),
            "planner_reasoning_summary": normalize_text(plan.get("reasoning_summary")),
            "runtime_skills_used": unique_values(plan.get("_runtime_skills_used", [])) if isinstance(plan.get("_runtime_skills_used"), list) else [],
            "runtime_skill_candidates": plan.get("_runtime_skill_candidates", []) if isinstance(plan.get("_runtime_skill_candidates"), list) else [],
            "runtime_skill_selection_reason": normalize_text(plan.get("_runtime_skill_selection_reason")),
            "active_runtime_skill": normalize_text(plan.get("_active_runtime_skill")),
            "runtime_skills_enabled": bool(plan.get("_runtime_skills_enabled", True)),
        }

    def _build_conversation_context(
        self,
        *,
        chat_session: dict[str, Any],
        message: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        backend, store, fallback_reason = self._resolve_context_store(user_id=user_id, session_id=session_id)
        local_store = LocalChatSessionEventStore()
        memory_hydrated = False
        memory_timeout = False
        memory_errors: list[str] = []
        memory_sync_status = "skipped"
        memory_latency_ms = 0.0

        should_hydrate = (
            backend == "agentbase"
            and self.chat_memory_hydrate_when_empty
            and bool(chat_session.get("_memory_hydrate_needed"))
        )
        if should_hydrate:
            hydrate_started = time.perf_counter()
            hydrate = self._run_with_timeout(
                lambda: store.list_recent_events(
                    chat_session=chat_session,
                    user_id=user_id,
                    session_id=session_id,
                    limit=self.chat_history_turn_limit,
                ),
                timeout_ms=self.chat_memory_timeout_ms,
            )
            memory_latency_ms += self._elapsed_ms(hydrate_started)
            if hydrate["timed_out"]:
                memory_timeout = True
                memory_errors.append("hydrate_timeout")
            elif hydrate["ok"]:
                hydrated_events = hydrate["result"] if isinstance(hydrate["result"], list) else []
                if hydrated_events:
                    self._merge_memory_events_into_chat_session(chat_session, hydrated_events)
                    memory_hydrated = True
            else:
                memory_errors.append(normalize_text(hydrate.get("error")) or "hydrate_error")
                if self.chat_context_backend == "agentbase" and not self.chat_context_fallback_on_error:
                    raise ValueError(f"AgentBase Memory context error: {hydrate.get('error')}")

        events = local_store.list_recent_events(
            chat_session=chat_session,
            user_id=user_id,
            session_id=session_id,
            limit=self.chat_history_turn_limit,
        )

        if backend == "agentbase":
            sync_started = time.perf_counter()
            sync = self._run_with_timeout(
                lambda: store.append_event(
                    chat_session=chat_session,
                    user_id=user_id,
                    session_id=session_id,
                    role="user",
                    content=message,
                ),
                timeout_ms=self.chat_memory_timeout_ms,
            )
            memory_latency_ms += self._elapsed_ms(sync_started)
            if sync["timed_out"]:
                memory_timeout = True
                memory_sync_status = "user_timeout"
            elif sync["ok"]:
                memory_sync_status = "user_synced"
            else:
                memory_sync_status = "user_error"
                memory_errors.append(normalize_text(sync.get("error")) or "user_sync_error")
                if self.chat_context_backend == "agentbase" and not self.chat_context_fallback_on_error:
                    raise ValueError(f"AgentBase Memory context error: {sync.get('error')}")
        elif backend == "local":
            memory_sync_status = "local_only"

        previous_events = self._previous_conversation_events(events, current_message=message)
        context_terms = self._extract_context_terms(previous_events)
        return {
            "backend": backend,
            "events": events,
            "previous_events": previous_events,
            "conversation_history": self._conversation_history_from_events(events),
            "context_terms": context_terms,
            "resolved_message": message,
            "raw_message": message,
            "used": bool(previous_events),
            "fallback_reason": fallback_reason,
            "user_id": user_id,
            "session_id": session_id,
            "memory_hydrated": memory_hydrated,
            "memory_sync_status": memory_sync_status,
            "memory_timeout": memory_timeout,
            "memory_errors": memory_errors,
            "memory_latency_ms": round(memory_latency_ms, 2),
        }

    def _run_with_timeout(self, func, *, timeout_ms: int) -> dict[str, Any]:
        result_queue: queue.Queue = queue.Queue(maxsize=1)

        def runner() -> None:
            try:
                result_queue.put({"ok": True, "result": func(), "error": "", "timed_out": False})
            except Exception as exc:  # pragma: no cover - exercised by fake stores in tests
                result_queue.put({"ok": False, "result": None, "error": normalize_text(str(exc)), "timed_out": False})

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(max(1, timeout_ms) / 1000)
        if thread.is_alive():
            return {"ok": False, "result": None, "error": "timeout", "timed_out": True}
        try:
            return result_queue.get_nowait()
        except queue.Empty:
            return {"ok": False, "result": None, "error": "no_result", "timed_out": False}

    def _merge_memory_events_into_chat_session(self, chat_session: dict[str, Any], events: list[dict[str, Any]]) -> None:
        current_messages = chat_session.get("messages", []) if isinstance(chat_session.get("messages"), list) else []
        merged: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for event in [*events, *current_messages]:
            role = normalize_text(event.get("role"))
            content = normalize_text(event.get("content"))
            created_at = normalize_text(event.get("created_at")) or now_iso()
            if not content:
                continue
            key = (role, content)
            if key in seen:
                continue
            seen.add(key)
            merged.append({"role": role, "content": content, "created_at": created_at})
        chat_session["messages"] = merged[-self.chat_history_turn_limit :]

    def _conversation_history_from_events(self, events: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "role": normalize_text(event.get("role")),
                "content": normalize_text(event.get("content")),
                "created_at": normalize_text(event.get("created_at")),
                "source": "session_mirror",
            }
            for event in events[-self.chat_history_turn_limit :]
            if normalize_text(event.get("content"))
        ]

    def _resolve_context_store(self, *, user_id: str, session_id: str) -> tuple[str, Any, str]:
        if self.chat_context_backend == "local":
            return "local", LocalChatSessionEventStore(), ""
        missing_identity = not normalize_text(user_id) or not normalize_text(session_id)
        if self.chat_context_backend == "agentbase":
            if missing_identity:
                raise ValueError("AgentBase Memory cần user_id và session_id để tách context theo session.")
            if not self.chat_context_memory_id:
                raise ValueError("Thiếu CHAT_CONTEXT_MEMORY_ID cho AgentBase Memory.")
            return "agentbase", AgentBaseMemoryEventStore(memory_id=self.chat_context_memory_id), ""

        if missing_identity or not self.chat_context_memory_id or MemoryClient is None:
            reason = "missing_user_or_session" if missing_identity else "memory_not_configured"
            return "local", LocalChatSessionEventStore(), reason
        return "agentbase", AgentBaseMemoryEventStore(memory_id=self.chat_context_memory_id), ""

    def _previous_conversation_events(self, events: list[dict[str, Any]], *, current_message: str) -> list[dict[str, Any]]:
        previous = list(events)
        if previous and previous[-1].get("role") == "user" and previous[-1].get("content") == current_message:
            previous = previous[:-1]
        return previous

    def _extract_context_terms(self, events: list[dict[str, Any]]) -> list[str]:
        terms: list[str] = []
        for event in reversed(events):
            content = normalize_text(event.get("content"))
            if not content:
                continue
            for acronym in extract_acronyms(content):
                if self._find_knowledge_by_name(acronym):
                    terms.append(acronym)
            if terms:
                break
        return unique_values(terms)

    def _get_or_create_chat_session(self, *, session_id: str, user_id: str) -> dict[str, Any]:
        data = self._load_chat_sessions()
        cleaned_id = normalize_text(session_id) or new_id("chat")
        session = copy.deepcopy(data["sessions"].get(cleaned_id))
        if session:
            if user_id and not session.get("user_id"):
                session["user_id"] = normalize_text(user_id)
            return session
        return {
            "id": cleaned_id,
            "user_id": normalize_text(user_id),
            "state": "idle",
            "messages": [],
            "pending_actions": {},
            "latest_pending_action_id": "",
            "active_teaching_session_id": "",
            "active_runtime_skill": "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

    def _save_chat_session(self, session: dict[str, Any]) -> None:
        session["state"] = self._chat_session_state(session)
        session["updated_at"] = now_iso()
        data = self._load_chat_sessions()
        persisted = copy.deepcopy(session)
        for key in [
            "_conversation_context",
            "_context_user_id",
            "_context_session_id",
            "_debug_context",
            "_use_runtime_skills",
            "_latency_ms",
            "_chat_started_at",
            "_memory_hydrate_needed",
        ]:
            persisted.pop(key, None)
        data["sessions"][session["id"]] = persisted
        self._save_json(self.chat_sessions_path, data)

    def _append_chat_message(self, session: dict[str, Any], *, role: str, content: str) -> None:
        session.setdefault("messages", [])
        session["messages"].append({"role": role, "content": normalize_text(content), "created_at": now_iso()})
        session["messages"] = session["messages"][-20:]

    def _pending_chat_actions(self, session: dict[str, Any], action_type: str = "") -> list[dict[str, Any]]:
        actions = []
        for action in session.get("pending_actions", {}).values():
            if action.get("status") != "pending":
                continue
            if action_type and action.get("type") != action_type:
                continue
            actions.append(action)
        return sorted(actions, key=lambda item: item.get("created_at", ""))

    def _pending_action_planner_summary(self, action: dict[str, Any]) -> dict[str, Any]:
        payload = action.get("payload", {}) if isinstance(action.get("payload"), dict) else {}
        summary = {
            "id": action.get("id", ""),
            "type": action.get("type", ""),
            "status": action.get("status", ""),
            "created_at": action.get("created_at", ""),
        }
        if action.get("type") == "data_query":
            summary.update(
                {
                    "current_query": normalize_text(payload.get("resolved_message") or payload.get("message")),
                    "raw_message": normalize_text(payload.get("raw_message")),
                    "context_terms": payload.get("context_terms", []) if isinstance(payload.get("context_terms"), list) else [],
                    "refinements": payload.get("refinements", []) if isinstance(payload.get("refinements"), list) else [],
                }
            )
        elif action.get("type") in {"start_teaching", "append_teaching"}:
            summary["message"] = normalize_text(payload.get("message"))
        elif action.get("type") == "commit_teaching":
            summary["teaching_session_id"] = normalize_text(payload.get("teaching_session_id"))
        else:
            summary["payload"] = payload
        return summary

    def _create_pending_chat_action(
        self,
        session: dict[str, Any],
        *,
        action_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._cancel_pending_chat_actions(session, reason="replaced_by_new_pending_action")
        action = {
            "id": new_id("act"),
            "type": action_type,
            "status": "pending",
            "payload": copy.deepcopy(payload),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        session.setdefault("pending_actions", {})[action["id"]] = action
        session["latest_pending_action_id"] = action["id"]
        return action

    def _cancel_pending_chat_actions(self, session: dict[str, Any], action_type: str = "", *, reason: str = "") -> None:
        for action in self._pending_chat_actions(session, action_type=action_type):
            action["status"] = "cancelled"
            action["updated_at"] = now_iso()
            if reason:
                action["cancel_reason"] = reason
        if not self._pending_chat_actions(session):
            session["latest_pending_action_id"] = ""

    def _cancel_active_pending_actions(self, session: dict[str, Any], *, reason: str) -> list[dict[str, Any]]:
        pending = self._pending_chat_actions(session)
        cancelled = []
        for action in pending:
            action["status"] = "cancelled"
            action["updated_at"] = now_iso()
            action["cancel_reason"] = reason
            cancelled.append(action)
        session["latest_pending_action_id"] = ""
        return cancelled

    def _build_pending_cancel_answer(self, cancelled: list[dict[str, Any]]) -> str:
        if not cancelled:
            return "Hiện không có pending action nào để hủy."
        if len(cancelled) == 1:
            action = cancelled[0]
            return f"Mình đã hủy pending action `{action['id']}` ({action['type']})."
        rendered = ", ".join(f"`{action['id']}` ({action['type']})" for action in cancelled)
        return f"Mình đã hủy {len(cancelled)} pending actions: {rendered}."

    def _handle_active_runtime_skill_cancel(self, *, chat_session: dict[str, Any], message: str) -> dict[str, Any]:
        active_skill = normalize_text(chat_session.get("active_runtime_skill"))
        if not active_skill or not self._is_chat_cancel(message):
            return {}
        chat_session["active_runtime_skill"] = ""
        return self._finalize_chat_response(
            {
                "status": "cancelled",
                "intent": "runtime_skill",
                "answer": f"Mình đã tắt chế độ `{active_skill}` cho session này.",
                "question": message,
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": {
                    "llm_used": False,
                    "fallback_used": False,
                    "active_runtime_skill_cancelled": active_skill,
                },
            },
            chat_session=chat_session,
            requires_confirmation=False,
        )

    def _handle_pending_status_query(self, *, chat_session: dict[str, Any], message: str) -> dict[str, Any]:
        if not self._is_pending_status_query(message):
            return {}
        pending = self._pending_chat_actions(chat_session)
        if not pending:
            answer = "Không có pending action nào đang chờ trong session này."
        else:
            action = self._latest_pending_chat_action(chat_session) or pending[-1]
            answer = self._render_pending_action_status(action)
        response = {
            "status": "answered",
            "intent": "pending_status",
            "answer": answer,
            "question": message,
            "missing": [],
            "used_knowledge_ids": [],
            "used_dictionary_ids": [],
            "used_example_ids": [],
            "debug": {
                "llm_used": False,
                "fallback_used": False,
                "pending_status_checked": True,
                "pending_count": len(pending),
            },
        }
        return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=bool(pending), pending_action=(self._latest_pending_chat_action(chat_session) if pending else None))

    def _render_pending_action_status(self, action: dict[str, Any]) -> str:
        payload = action.get("payload", {}) if isinstance(action.get("payload"), dict) else {}
        if action.get("type") == "data_query":
            query = normalize_text(payload.get("resolved_message") or payload.get("message") or payload.get("raw_message"))
            return f"Đang có 1 pending data query chờ confirm: `{query}`. Pending action id: `{action['id']}`."
        if action.get("type") in {"start_teaching", "append_teaching"}:
            message = normalize_text(payload.get("message"))
            return f"Đang có 1 pending teaching action chờ confirm: `{message}`. Pending action id: `{action['id']}`."
        if action.get("type") == "commit_teaching":
            teaching_session_id = normalize_text(payload.get("teaching_session_id"))
            return f"Đang có 1 pending commit teaching chờ confirm cho session `{teaching_session_id}`. Pending action id: `{action['id']}`."
        return f"Đang có 1 pending action `{action.get('type')}` chờ confirm. Pending action id: `{action['id']}`."

    def _handle_chat_confirmation(
        self,
        *,
        chat_session: dict[str, Any],
        message: str,
        pending_action_id: str = "",
    ) -> dict[str, Any]:
        if not (self._is_chat_confirmation(message) or self._is_chat_cancel(message) or normalize_text(pending_action_id)):
            return {}
        pending = self._pending_chat_actions(chat_session)
        if not pending:
            return {}

        target_id = normalize_text(pending_action_id)
        if target_id:
            targets = [action for action in pending if action["id"] == target_id]
            if not targets:
                return self._finalize_chat_response(
                    {
                        "status": "needs_clarification",
                        "intent": "clarification",
                        "answer": f"Mình không tìm thấy pending action `{target_id}` trong session này.",
                        "question": message,
                        "missing": [],
                        "used_knowledge_ids": [],
                        "used_dictionary_ids": [],
                        "used_example_ids": [],
                        "debug": {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
                    },
                    chat_session=chat_session,
                    requires_confirmation=False,
                )
        else:
            targets = [self._latest_pending_chat_action(chat_session) or pending[-1]]

        action = targets[0]
        if self._is_chat_cancel(message):
            cancelled = self._cancel_active_pending_actions(chat_session, reason="user_cancelled")
            return self._finalize_chat_response(
                {
                    "status": "cancelled",
                    "intent": action.get("type", "cancel_action"),
                    "answer": self._build_pending_cancel_answer(cancelled),
                    "question": message,
                    "missing": [],
                    "used_knowledge_ids": [],
                    "used_dictionary_ids": [],
                    "used_example_ids": [],
                    "debug": {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
                },
                chat_session=chat_session,
                requires_confirmation=False,
            )
        for other in pending:
            if other.get("id") != action.get("id"):
                other["status"] = "cancelled"
                other["updated_at"] = now_iso()
                other["cancel_reason"] = "superseded_by_confirmed_latest_pending_action"
        if not self._is_chat_confirmation(message):
            return {}
        return self._confirm_chat_action(chat_session=chat_session, action=action, message=message)

    def _handle_pending_action_refinement(
        self,
        *,
        chat_session: dict[str, Any],
        message: str,
    ) -> dict[str, Any]:
        pending = self._pending_chat_actions(chat_session)
        if len(pending) != 1:
            return {}
        action = pending[0]
        if action.get("type") != "data_query":
            return {}
        if not self._looks_like_data_query_refinement(message):
            return {}
        return self._refine_pending_data_query_action(
            chat_session=chat_session,
            message=message,
            pending_action_id=action.get("id", ""),
        )

    def _refine_pending_data_query_action(
        self,
        *,
        chat_session: dict[str, Any],
        message: str,
        pending_action_id: str = "",
        planner_answer: str = "",
        planner_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pending = self._pending_chat_actions(chat_session, action_type="data_query")
        if pending_action_id:
            pending = [action for action in pending if action.get("id") == pending_action_id]
        if not pending:
            response = {
                "status": "needs_clarification",
                "intent": "clarification",
                "answer": planner_answer or "Mình chưa thấy data query nào đang pending để cập nhật.",
                "question": message,
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": planner_debug or {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
            }
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)
        if len(pending) > 1:
            rendered = ", ".join(f"{action['id']}:{action['type']}" for action in pending)
            response = {
                "status": "needs_clarification",
                "intent": "clarification",
                "answer": f"Session này đang có nhiều pending data queries: {rendered}. Bạn gửi kèm pending_action_id muốn cập nhật nhé.",
                "question": message,
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": planner_debug or {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
            }
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)
        action = pending[0]
        payload = action.get("payload", {}) if isinstance(action.get("payload"), dict) else {}
        previous_message = normalize_text(payload.get("resolved_message") or payload.get("message") or payload.get("raw_message"))
        if not previous_message:
            return {}
        refined_message = self._merge_data_query_refinement(previous_message=previous_message, refinement=message)
        payload["message"] = refined_message
        payload["resolved_message"] = refined_message
        payload.setdefault("raw_message", previous_message)
        payload.setdefault("refinements", [])
        if isinstance(payload["refinements"], list):
            payload["refinements"].append({"message": message, "created_at": now_iso()})
        action["payload"] = payload
        action["updated_at"] = now_iso()
        natural_query = refined_message.replace(". Bổ sung:", ", ").replace("?.", "?").strip()
        response = {
            "status": "needs_confirmation",
            "intent": "data_sql",
            "answer": (
                f"Ok, mình hiểu yêu cầu hiện tại là: {natural_query}. "
                "Trước khi mình tạo phần data/draft SQL, bạn xác nhận giúp mình nhé. "
                "Nếu còn muốn đổi thời gian, cách tính, hoặc chiều breakdown thì cứ nhắn thêm."
            ),
            "question": refined_message,
            "missing": [
                {
                    "type": "confirmation",
                    "concept": "data_query",
                    "question": "Bạn confirm mình xử lý data query đã cập nhật này chứ?",
                }
            ],
            "used_knowledge_ids": [],
            "used_dictionary_ids": [],
            "used_example_ids": [],
            "debug": {
                **(planner_debug or {"llm_used": False, "fallback_used": False}),
                "pending_action_refined": True,
                "refined_pending_action_id": action["id"],
            },
        }
        return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=True, pending_action=action)

    def _merge_data_query_refinement(self, *, previous_message: str, refinement: str) -> str:
        previous = normalize_text(previous_message)
        addition = normalize_text(refinement)
        if not addition:
            return previous
        if self._looks_like_data_query_refinement(addition):
            return f"{previous}. Bổ sung: {addition}"
        return addition

    def _looks_like_data_query_refinement(self, message: str) -> bool:
        lowered = normalize_lookup(message)
        markers = [
            "xếp hạng",
            "rank",
            "theo ",
            "transid",
            "số giao dịch",
            "paying user",
            "tpv",
            "doanh thu",
            "top ",
            "provider",
            "route",
            "tháng",
            "ngày",
            "time range",
        ]
        return any(marker in lowered for marker in markers)

    def _data_query_clarification_items(self, message: str) -> list[dict[str, str]]:
        lowered = normalize_lookup(message)
        missing: list[dict[str, str]] = []
        if not self._has_data_time_range(lowered):
            missing.append(
                {
                    "type": "clarification",
                    "concept": "time_range",
                    "question": "Bạn muốn lấy số liệu cho khoảng thời gian nào?",
                }
            )
        if not self._has_data_output_shape(lowered):
            missing.append(
                {
                    "type": "clarification",
                    "concept": "output_shape",
                    "question": "Bạn muốn xem số tổng, xu hướng theo ngày/tuần/tháng, hay breakdown theo chiều nào?",
                }
            )
        return missing

    def _has_data_time_range(self, lowered_message: str) -> bool:
        time_markers = [
            "hom nay",
            "hôm nay",
            "hom qua",
            "hôm qua",
            "tuan nay",
            "tuần này",
            "thang nay",
            "tháng này",
            "quy nay",
            "quý này",
            "nam nay",
            "năm nay",
            "last ",
            "recent ",
            "yesterday",
            "today",
            "week",
            "month",
            "quarter",
            "year",
            "ngay ",
            "ngày ",
            "tuan ",
            "tuần ",
            "thang ",
            "tháng ",
            "quy ",
            "quý ",
            "nam ",
            "năm ",
        ]
        if any(marker in lowered_message for marker in time_markers):
            return True
        return bool(re.search(r"\b(20\d{2}|q[1-4]|m[0-9]{1,2}|[0-9]{1,2}/[0-9]{1,2})\b", lowered_message))

    def _has_data_output_shape(self, lowered_message: str) -> bool:
        shape_markers = [
            "theo ",
            "by ",
            "group by",
            "breakdown",
            "xu huong",
            "xu hướng",
            "trend",
            "top ",
            "rank",
            "xep hang",
            "xếp hạng",
            "tong ",
            "tổng ",
            "total",
            "average",
            "trung binh",
            "trung bình",
            "so sanh",
            "so sánh",
        ]
        if any(marker in lowered_message for marker in shape_markers):
            return True
        vague_number_markers = ["mot vai so", "một vài số", "vai so", "vài số", "some numbers"]
        return not any(marker in lowered_message for marker in vague_number_markers)

    def _confirm_chat_action(self, *, chat_session: dict[str, Any], action: dict[str, Any], message: str) -> dict[str, Any]:
        action_type = action.get("type", "")
        payload = action.get("payload", {}) if isinstance(action.get("payload"), dict) else {}
        action["status"] = "confirmed"
        action["updated_at"] = now_iso()

        if action_type == "start_teaching":
            result = self.start_teach_session(
                message=payload.get("message", ""),
                stakeholder=chat_session.get("user_id", ""),
                owner=chat_session.get("user_id", ""),
            )
            chat_session["active_teaching_session_id"] = result["session_id"]
            action["status"] = "done"
            commit_action = self._create_commit_teaching_action(chat_session, teaching_session_id=result["session_id"])
            response = {
                "status": result.get("status", "clarifying"),
                "intent": "teach_knowledge",
                "answer": self._build_teaching_chat_answer(result),
                "question": message,
                "session_id": result["session_id"],
                "teaching_session": result.get("session"),
                "draft": result.get("draft"),
                "summary": result.get("summary"),
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
            }
            return self._finalize_chat_response(
                response,
                chat_session=chat_session,
                requires_confirmation=True,
                pending_action=commit_action,
            )

        if action_type == "append_teaching":
            teaching_session_id = payload.get("teaching_session_id") or chat_session.get("active_teaching_session_id", "")
            result = self.append_teach_message(session_id=teaching_session_id, message=payload.get("message", ""))
            action["status"] = "done"
            commit_action = self._create_commit_teaching_action(chat_session, teaching_session_id=teaching_session_id)
            response = {
                "status": result.get("status", "clarifying"),
                "intent": "teach_knowledge",
                "answer": self._build_teaching_chat_answer(result),
                "question": message,
                "session_id": teaching_session_id,
                "teaching_session": result.get("session"),
                "draft": result.get("draft"),
                "summary": result.get("summary"),
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
            }
            return self._finalize_chat_response(
                response,
                chat_session=chat_session,
                requires_confirmation=True,
                pending_action=commit_action,
            )

        if action_type == "commit_teaching":
            teaching_session_id = payload.get("teaching_session_id") or chat_session.get("active_teaching_session_id", "")
            result = self.confirm_teach_session(session_id=teaching_session_id, decision="confirm")
            action["status"] = "done"
            chat_session["active_teaching_session_id"] = ""
            answer = (
                f"Đã ghi {len(result.get('knowledge_created', []))} knowledge mới vào KB."
                if result.get("knowledge_created")
                else f"Đã tạo {len(result.get('change_requests', []))} pending change cần review."
                if result.get("change_requests")
                else "Teaching session đã kết thúc."
            )
            response = {
                "status": result.get("session", {}).get("status", "committed"),
                "intent": "teach_knowledge",
                "answer": answer,
                "question": message,
                "session_id": teaching_session_id,
                "teaching_session": result.get("session"),
                "knowledge_created": result.get("knowledge_created", []),
                "change_requests": result.get("change_requests", []),
                "missing": [],
                "used_knowledge_ids": [item["id"] for item in result.get("knowledge_created", [])],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
            }
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)

        if action_type == "data_query":
            result = self.ask_data_question(payload.get("message", ""))
            action["status"] = "done"
            response = {
                "status": result.get("status", "answered"),
                "intent": "data_sql",
                "answer": self._synthesize_data_answer(payload.get("message", ""), result),
                "question": payload.get("message", ""),
                "sql": result.get("sql"),
                "missing": result.get("missing", []),
                "used_knowledge_ids": result.get("used_knowledge_ids")
                or [item["id"] for item in result.get("known_knowledge", result.get("knowledge", []))],
                "used_dictionary_ids": result.get("used_dictionary_ids", []),
                "used_example_ids": result.get("used_example_ids", []),
                "knowledge": result.get("known_knowledge", result.get("knowledge", [])),
                "dictionary": result.get("dictionary", []),
                "examples": result.get("examples", []),
                "debug": {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
            }
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)

        return self._finalize_chat_response(
            {
                "status": "error",
                "intent": action_type or "unknown",
                "answer": f"Pending action type chưa được hỗ trợ: {action_type}",
                "question": message,
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": {"llm_used": self._llm_configured(), "fallback_used": not self._llm_configured()},
            },
            chat_session=chat_session,
            requires_confirmation=False,
        )

    def _create_commit_teaching_action(self, chat_session: dict[str, Any], *, teaching_session_id: str) -> dict[str, Any]:
        self._cancel_pending_chat_actions(chat_session, action_type="commit_teaching", reason="replaced_by_new_draft")
        return self._create_pending_chat_action(
            chat_session,
            action_type="commit_teaching",
            payload={"teaching_session_id": teaching_session_id},
        )

    def _propose_data_query_action(
        self,
        *,
        chat_session: dict[str, Any],
        message: str,
        raw_message: str = "",
        context: dict[str, Any],
        conversation_context: dict[str, Any] | None = None,
        llm_used: bool,
        planner_answer: str = "",
        planner_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conversation_context = conversation_context or {}
        clarification_items = self._data_query_clarification_items(message)
        if clarification_items:
            prefix = (normalize_text(planner_answer) + " ") if normalize_text(planner_answer) else ""
            debug = planner_debug or {"llm_used": llm_used, "fallback_used": not llm_used}
            response = {
                "status": "needs_clarification",
                "intent": "data_sql",
                "answer": (
                    prefix
                    + "Mình cần bạn làm rõ thêm trước khi tạo yêu cầu data: "
                    + " ".join(item["question"] for item in clarification_items)
                ),
                "question": message,
                "missing": clarification_items,
                "used_knowledge_ids": [item["id"] for item in context.get("knowledge", [])],
                "used_dictionary_ids": [item["id"] for item in context.get("dictionary", [])],
                "used_example_ids": [item["id"] for item in context.get("examples", [])],
                "debug": {**debug, "data_query_clarification_before_confirmation": True},
            }
            self._attach_debug_context(response, context=context, chat_session=chat_session)
            return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=False)
        action = self._create_pending_chat_action(
            chat_session,
            action_type="data_query",
            payload={
                "message": message,
                "raw_message": raw_message or message,
                "resolved_message": message,
                "user_id": conversation_context.get("user_id", chat_session.get("user_id", "")),
                "session_id": conversation_context.get("session_id", chat_session.get("id", "")),
                "context_terms": conversation_context.get("context_terms", []),
            },
        )
        prefix = (normalize_text(planner_answer) + " ") if normalize_text(planner_answer) else ""
        debug = planner_debug or {"llm_used": llm_used, "fallback_used": not llm_used}
        response = {
            "status": "needs_confirmation",
            "intent": "data_sql",
            "answer": (
                prefix
                + "Mình có thể chuẩn bị phần data/draft SQL cho câu này. "
                "Trước khi xử lý, bạn xác nhận giúp mình nhé; nếu muốn đổi thời gian, cách tính, hoặc chiều breakdown thì cứ nhắn thêm."
            ),
            "question": message,
            "missing": [
                {
                    "type": "confirmation",
                    "concept": "data_query",
                    "question": "Bạn confirm mình xử lý phần query data/draft SQL chứ?",
                }
            ],
            "used_knowledge_ids": [item["id"] for item in context.get("knowledge", [])],
            "used_dictionary_ids": [item["id"] for item in context.get("dictionary", [])],
            "used_example_ids": [item["id"] for item in context.get("examples", [])],
            "debug": debug,
        }
        self._attach_debug_context(response, context=context, chat_session=chat_session)
        return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=True, pending_action=action)

    def _propose_teaching_action(
        self,
        *,
        chat_session: dict[str, Any],
        message: str,
        llm_used: bool,
        planner_answer: str = "",
        planner_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = self._create_pending_chat_action(chat_session, action_type="start_teaching", payload={"message": message})
        debug = planner_debug or {"llm_used": llm_used, "fallback_used": not llm_used}
        response = {
            "status": "needs_confirmation",
            "intent": "teach_knowledge",
            "answer": normalize_text(planner_answer) or (
                "Mình hiểu câu này có vẻ là bạn đang muốn dạy knowledge mới. "
                "Bạn confirm mình bắt đầu teaching session từ nội dung này chứ?"
            ),
            "question": message,
            "missing": [
                {
                    "type": "confirmation",
                    "concept": "start_teaching",
                    "question": "Bạn muốn mình bắt đầu teaching session từ nội dung này không?",
                }
            ],
            "used_knowledge_ids": [],
            "used_dictionary_ids": [],
            "used_example_ids": [],
            "debug": debug,
        }
        return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=True, pending_action=action)

    def _propose_append_teaching_action(
        self,
        *,
        chat_session: dict[str, Any],
        message: str,
        llm_used: bool,
        planner_answer: str = "",
        planner_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._cancel_pending_chat_actions(chat_session, action_type="commit_teaching", reason="draft_append_requested")
        action = self._create_pending_chat_action(
            chat_session,
            action_type="append_teaching",
            payload={"message": message, "teaching_session_id": chat_session.get("active_teaching_session_id", "")},
        )
        debug = planner_debug or {"llm_used": llm_used, "fallback_used": not llm_used}
        response = {
            "status": "needs_confirmation",
            "intent": "teach_knowledge",
            "answer": normalize_text(planner_answer) or "Mình hiểu đây có thể là phần bổ sung cho draft knowledge đang dạy. Bạn confirm mình append nội dung này vào draft chứ?",
            "question": message,
            "missing": [
                {
                    "type": "confirmation",
                    "concept": "append_teaching",
                    "question": "Bạn muốn append nội dung này vào draft đang dạy không?",
                }
            ],
            "used_knowledge_ids": [],
            "used_dictionary_ids": [],
            "used_example_ids": [],
            "debug": debug,
        }
        return self._finalize_chat_response(response, chat_session=chat_session, requires_confirmation=True, pending_action=action)

    def _finalize_chat_response(
        self,
        response: dict[str, Any],
        *,
        chat_session: dict[str, Any],
        requires_confirmation: bool,
        pending_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pending_action = pending_action or self._latest_pending_chat_action(chat_session)
        conversation_context = chat_session.get("_conversation_context") if isinstance(chat_session.get("_conversation_context"), dict) else {}
        response.setdefault("missing", [])
        response.setdefault("used_knowledge_ids", [])
        response.setdefault("used_dictionary_ids", [])
        response.setdefault("used_example_ids", [])
        response["chat_session_id"] = chat_session["id"]
        response["requires_confirmation"] = bool(requires_confirmation)
        response["pending_action_id"] = pending_action.get("id", "") if pending_action else ""
        response["pending_action_type"] = pending_action.get("type", "") if pending_action else ""
        response["confirm_options"] = ["confirm", "cancel"] if pending_action else []
        response["session_state"] = self._chat_session_state(chat_session)
        response["resolved_question"] = response.get("question") or conversation_context.get("resolved_message") or ""
        response["conversation_context_used"] = bool(conversation_context.get("used"))
        response["context_terms"] = conversation_context.get("context_terms", [])
        response["context_backend"] = conversation_context.get("backend") or self.chat_context_backend
        if conversation_context.get("fallback_reason"):
            response.setdefault("debug", {})["context_fallback_reason"] = conversation_context["fallback_reason"]
        self._apply_chat_answer_synthesis(response, chat_session=chat_session, pending_action=pending_action)
        self._append_assistant_context_event(chat_session, response.get("answer", ""))
        debug = response.setdefault("debug", {})
        debug["latency_ms"] = chat_session.get("_latency_ms", {})
        debug["conversation_history_used"] = bool(conversation_context.get("conversation_history"))
        debug["conversation_history_turns"] = len(conversation_context.get("conversation_history", []))
        debug["memory_hydrated"] = bool(conversation_context.get("memory_hydrated"))
        debug["memory_sync_status"] = conversation_context.get("memory_sync_status", "")
        debug["memory_timeout"] = bool(conversation_context.get("memory_timeout"))
        debug["memory_latency_ms"] = conversation_context.get("memory_latency_ms", 0)
        if conversation_context.get("memory_errors"):
            debug["memory_errors"] = conversation_context.get("memory_errors")
        return response

    def _apply_chat_answer_synthesis(
        self,
        response: dict[str, Any],
        *,
        chat_session: dict[str, Any],
        pending_action: dict[str, Any] | None = None,
    ) -> None:
        debug = response.setdefault("debug", {})
        if not self._llm_configured():
            debug["answer_synthesis_used"] = False
            debug["answer_synthesis_fallback_reason"] = "llm_not_configured"
            response["answer"] = self._sanitize_user_answer(normalize_text(response.get("answer")))
            return

        fallback_answer = self._sanitize_user_answer(normalize_text(response.get("answer")))
        payload = self._answer_synthesis_payload(response=response, chat_session=chat_session, pending_action=pending_action)
        try:
            synthesized = self.llm_client.complete_text(
                system=(
                    "You write the final user-facing answer for a Vietnamese business data agent. "
                    "The Python state is already locked; do not change status, do not claim actions were executed, "
                    "do not invent data, SQL, tables, columns, or metric definitions. "
                    "Use the given locked_state, missing fields, and pending_action to write a natural answer. "
                    "Never expose raw pending_action_id, internal state names, JSON, debug fields, or implementation details. "
                    "When status is needs_dictionary or needs_knowledge, do not include SQL or claim the query is ready. "
                    "If confirmation is required, naturally ask the user to confirm and mention they can still adjust details. "
                    "If clarification is required, ask concise concrete questions. "
                    "If runtime skill instructions are present, follow them for tone/protocol."
                ),
                user=json.dumps(payload, ensure_ascii=False),
                temperature=0.2,
            )
        except (error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            debug["answer_synthesis_used"] = False
            debug["answer_synthesis_fallback_reason"] = "llm_error"
            response["answer"] = fallback_answer
            return

        cleaned = self._sanitize_user_answer(synthesized)
        if not cleaned:
            debug["answer_synthesis_used"] = False
            debug["answer_synthesis_fallback_reason"] = "empty_answer"
            response["answer"] = fallback_answer
            return
        if self._answer_violates_locked_state(response, cleaned):
            debug["answer_synthesis_used"] = False
            debug["answer_synthesis_fallback_reason"] = "invalid_locked_state"
            response["answer"] = fallback_answer
            return
        response["answer"] = cleaned
        debug["answer_synthesis_used"] = True
        debug["answer_synthesis_fallback_reason"] = ""

    def _answer_synthesis_payload(
        self,
        *,
        response: dict[str, Any],
        chat_session: dict[str, Any],
        pending_action: dict[str, Any] | None,
    ) -> dict[str, Any]:
        conversation_context = chat_session.get("_conversation_context") if isinstance(chat_session.get("_conversation_context"), dict) else {}
        runtime_skills = []
        active_skill_name = normalize_text(chat_session.get("active_runtime_skill"))
        if active_skill_name:
            registry = RuntimeSkillRegistry()
            active_skill = self._runtime_skill_by_name(registry, active_skill_name)
            if active_skill:
                runtime_skills.append(registry.skill_payload(active_skill))
        return {
            "user_message": response.get("question", ""),
            "draft_answer": response.get("answer", ""),
            "locked_state": {
                "status": response.get("status", ""),
                "intent": response.get("intent", ""),
                "requires_confirmation": bool(response.get("requires_confirmation")),
                "pending_action_type": response.get("pending_action_type", ""),
                "session_state": response.get("session_state", ""),
            },
            "pending_action": self._pending_action_planner_summary(pending_action) if pending_action else {},
            "missing": response.get("missing", []),
            "sql": response.get("sql") or "",
            "knowledge": [self._compact_planner_knowledge(item) for item in response.get("knowledge", [])[:5]],
            "dictionary": [self._compact_planner_dictionary(item) for item in response.get("dictionary", [])[:3]],
            "examples": [self._compact_planner_example(item) for item in response.get("examples", [])[:3]],
            "used_ids": {
                "knowledge": response.get("used_knowledge_ids", []),
                "dictionary": response.get("used_dictionary_ids", []),
                "examples": response.get("used_example_ids", []),
            },
            "conversation": {
                "history": conversation_context.get("conversation_history", [])[-6:],
                "context_terms": conversation_context.get("context_terms", []),
                "backend": conversation_context.get("backend", ""),
            },
            "runtime_skills": runtime_skills,
        }

    def _sanitize_user_answer(self, answer: str) -> str:
        cleaned = normalize_text(answer)
        cleaned = re.sub(r"`?pending_action_id\s*=\s*[^`\s,.;]+`?", "yêu cầu đang chờ xác nhận", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"Pending action id:\s*`?[^`\s,.;]+`?", "Yêu cầu này đang chờ xác nhận.", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _answer_violates_locked_state(self, response: dict[str, Any], answer: str) -> bool:
        status = normalize_text(response.get("status"))
        lowered = normalize_lookup(answer)
        if status in {"needs_dictionary", "needs_knowledge"}:
            return "```sql" in lowered or bool(re.search(r"\bselect\b.+\bfrom\b", lowered, flags=re.IGNORECASE | re.DOTALL))
        return False

    def _elapsed_ms(self, started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 2)

    def _record_chat_latency(self, chat_session: dict[str, Any], key: str, started_at: float) -> None:
        latency = chat_session.get("_latency_ms")
        if not isinstance(latency, dict):
            latency = {}
            chat_session["_latency_ms"] = latency
        latency[key] = self._elapsed_ms(started_at)

    def _record_chat_total_latency(self, chat_session: dict[str, Any]) -> None:
        started_at = chat_session.get("_chat_started_at")
        if isinstance(started_at, (int, float)):
            self._record_chat_latency(chat_session, "total", float(started_at))

    def _attach_debug_context(self, response: dict[str, Any], *, context: dict[str, Any], chat_session: dict[str, Any]) -> None:
        if not chat_session.get("_debug_context"):
            return
        response["knowledge"] = context.get("knowledge", [])
        response["dictionary"] = context.get("dictionary", [])
        response["examples"] = context.get("examples", [])

    def _append_assistant_context_event(self, chat_session: dict[str, Any], answer: str) -> None:
        content = normalize_text(answer)
        if not content:
            return
        self._append_chat_message(chat_session, role="assistant", content=content)
        user_id = normalize_text(chat_session.get("_context_user_id") or chat_session.get("user_id"))
        session_id = normalize_text(chat_session.get("_context_session_id") or chat_session.get("id"))
        backend, store, _fallback_reason = self._resolve_context_store(user_id=user_id, session_id=session_id)
        if backend != "agentbase":
            return
        sync_started = time.perf_counter()
        sync = self._run_with_timeout(
            lambda: store.append_event(
                chat_session=chat_session,
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=content,
            ),
            timeout_ms=self.chat_memory_timeout_ms,
        )
        conversation_context = chat_session.get("_conversation_context") if isinstance(chat_session.get("_conversation_context"), dict) else {}
        previous_status = normalize_text(conversation_context.get("memory_sync_status"))
        elapsed = self._elapsed_ms(sync_started)
        conversation_context["memory_latency_ms"] = round(float(conversation_context.get("memory_latency_ms") or 0) + elapsed, 2)
        if sync["timed_out"]:
            conversation_context["memory_timeout"] = True
            assistant_status = "assistant_timeout"
        elif sync["ok"]:
            assistant_status = "assistant_synced"
        else:
            assistant_status = "assistant_error"
            conversation_context.setdefault("memory_errors", []).append(normalize_text(sync.get("error")) or "assistant_sync_error")
            if not self.chat_context_fallback_on_error:
                raise ValueError(f"AgentBase Memory context error: {sync.get('error')}")
        conversation_context["memory_sync_status"] = " + ".join([item for item in [previous_status, assistant_status] if item])

    def _latest_pending_chat_action(self, chat_session: dict[str, Any]) -> dict[str, Any]:
        latest_id = chat_session.get("latest_pending_action_id", "")
        latest = chat_session.get("pending_actions", {}).get(latest_id)
        if latest and latest.get("status") == "pending":
            return latest
        pending = self._pending_chat_actions(chat_session)
        return pending[-1] if pending else {}

    def _chat_session_state(self, chat_session: dict[str, Any]) -> str:
        latest = self._latest_pending_chat_action(chat_session)
        if latest.get("type") == "data_query":
            return "data_query_pending"
        if latest.get("type") == "start_teaching":
            return "teaching_pending"
        if latest.get("type") in {"append_teaching", "commit_teaching"}:
            return "teaching_draft_active"
        if chat_session.get("active_teaching_session_id"):
            return "teaching_draft_active"
        return "idle"

    def _chat_propose_teaching_session(self, *, message: str, user_id: str, llm_used: bool) -> dict[str, Any]:
        session = {
            "id": new_id("teach"),
            "status": "awaiting_teach_confirmation",
            "messages": [{"role": "user", "content": message, "created_at": now_iso()}],
            "draft": {},
            "stakeholder": normalize_text(user_id),
            "team": "",
            "domain": "",
            "owner": normalize_text(user_id),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        self._save_teaching_session(session)
        return {
            "status": "needs_confirmation",
            "intent": "teach_knowledge",
            "answer": (
                "Mình hiểu câu này có vẻ là bạn đang muốn dạy knowledge mới. "
                "Bạn confirm mình bắt đầu teaching session từ nội dung này chứ? "
                "Nếu đồng ý, nhắn `confirm` với cùng `session_id`; nếu không thì nhắn `cancel`."
            ),
            "question": message,
            "session_id": session["id"],
            "teaching_session": copy.deepcopy(session),
            "draft": {},
            "summary": {},
            "missing": [
                {
                    "type": "confirmation",
                    "concept": "teach_knowledge",
                    "question": "Bạn muốn mình bắt đầu teaching session từ nội dung này không?",
                }
            ],
            "used_knowledge_ids": [],
            "used_dictionary_ids": [],
            "used_example_ids": [],
            "debug": {"llm_used": llm_used, "fallback_used": not llm_used},
        }

    def _chat_continue_teaching_session(
        self,
        *,
        message: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        cleaned_session_id = normalize_text(session_id)
        if not cleaned_session_id:
            return {}
        try:
            session = self._get_teaching_session(cleaned_session_id)
        except ValueError:
            return {}
        if session.get("status") in {"committed", "pending_approval", "cancelled"}:
            return {}

        llm_used = self._llm_configured()
        if session.get("status") == "awaiting_teach_confirmation":
            if self._is_chat_cancel(message):
                session["status"] = "cancelled"
                session["updated_at"] = now_iso()
                self._save_teaching_session(session)
                return {
                    "status": "cancelled",
                    "intent": "teach_knowledge",
                    "answer": "Mình đã hủy đề xuất dạy knowledge này, chưa parse và chưa ghi gì vào KB.",
                    "question": message,
                    "session_id": cleaned_session_id,
                    "teaching_session": copy.deepcopy(session),
                    "missing": [],
                    "used_knowledge_ids": [],
                    "used_dictionary_ids": [],
                    "used_example_ids": [],
                    "debug": {"llm_used": llm_used, "fallback_used": not llm_used},
                }
            if not self._is_chat_confirmation(message):
                return {
                    "status": "needs_confirmation",
                    "intent": "teach_knowledge",
                    "answer": "Mình vẫn đang chờ bạn confirm có bắt đầu teaching session từ nội dung trước đó không. Nhắn `confirm` hoặc `cancel` nhé.",
                    "question": message,
                    "session_id": cleaned_session_id,
                    "teaching_session": copy.deepcopy(session),
                    "missing": [
                        {
                            "type": "confirmation",
                            "concept": "teach_knowledge",
                            "question": "Bạn muốn bắt đầu teaching session từ nội dung trước đó không?",
                        }
                    ],
                    "used_knowledge_ids": [],
                    "used_dictionary_ids": [],
                    "used_example_ids": [],
                    "debug": {"llm_used": llm_used, "fallback_used": not llm_used},
                }
            session["status"] = "clarifying"
            session = self._refresh_teaching_session(session)
            self._save_teaching_session(session)
            result = self._teaching_session_response(session)
            return {
                "status": result.get("status", "clarifying"),
                "intent": "teach_knowledge",
                "answer": self._build_teaching_chat_answer(result),
                "question": message,
                "session_id": cleaned_session_id,
                "teaching_session": result.get("session"),
                "draft": result.get("draft"),
                "summary": result.get("summary"),
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": {"llm_used": llm_used, "fallback_used": not llm_used},
            }

        if self._is_chat_cancel(message):
            result = self.confirm_teach_session(session_id=cleaned_session_id, decision="cancel")
            return {
                "status": "cancelled",
                "intent": "teach_knowledge",
                "answer": "Mình đã hủy teaching session này, chưa ghi gì vào KB.",
                "question": message,
                "session_id": cleaned_session_id,
                "teaching_session": result.get("session"),
                "missing": [],
                "used_knowledge_ids": [],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": {"llm_used": llm_used, "fallback_used": not llm_used},
            }
        if self._is_chat_confirmation(message):
            result = self.confirm_teach_session(session_id=cleaned_session_id, decision="confirm")
            answer = (
                f"Đã ghi {len(result.get('knowledge_created', []))} knowledge mới vào KB."
                if result.get("knowledge_created")
                else f"Đã tạo {len(result.get('change_requests', []))} pending change cần review."
                if result.get("change_requests")
                else "Teaching session đã kết thúc."
            )
            return {
                "status": result.get("session", {}).get("status", "committed"),
                "intent": "teach_knowledge",
                "answer": answer,
                "question": message,
                "session_id": cleaned_session_id,
                "teaching_session": result.get("session"),
                "knowledge_created": result.get("knowledge_created", []),
                "change_requests": result.get("change_requests", []),
                "missing": [],
                "used_knowledge_ids": [item["id"] for item in result.get("knowledge_created", [])],
                "used_dictionary_ids": [],
                "used_example_ids": [],
                "debug": {"llm_used": llm_used, "fallback_used": not llm_used},
            }
        if self._is_chat_summary_request(message):
            result = self.summarize_teach_session(session_id=cleaned_session_id)
        else:
            result = self.append_teach_message(session_id=cleaned_session_id, message=message)
        return {
            "status": result.get("status", "clarifying"),
            "intent": "teach_knowledge",
            "answer": self._build_teaching_chat_answer(result),
            "question": message,
            "session_id": cleaned_session_id,
            "teaching_session": result.get("session"),
            "draft": result.get("draft"),
            "summary": result.get("summary"),
            "missing": [],
            "used_knowledge_ids": [],
            "used_dictionary_ids": [],
            "used_example_ids": [],
            "debug": {"llm_used": llm_used, "fallback_used": not llm_used},
        }

    def _build_teaching_chat_answer(self, result: dict[str, Any]) -> str:
        if result.get("status") == "awaiting_confirmation":
            summary = result.get("summary") or {}
            term = summary.get("term") or result.get("draft", {}).get("name", "")
            definition = summary.get("definition") or result.get("draft", {}).get("definition", "")
            formula = summary.get("formula") or result.get("draft", {}).get("formula")
            parts = [f"Mình hiểu bạn muốn dạy `{term}`: {definition}"] if term or definition else ["Mình đã tóm tắt được draft knowledge."]
            if formula:
                parts.append(f"Công thức/logic: {formula}.")
            parts.append("Bạn nhắn `confirm` để ghi vào KB, hoặc bổ sung thêm nếu còn thiếu.")
            return " ".join(parts)
        question = result.get("question")
        if question:
            return f"Mình cần làm rõ thêm trước khi ghi vào KB: {question}"
        return "Mình đã nhận thêm thông tin. Bạn có thể nhắn `tóm tắt` để xem draft hoặc `confirm` để ghi vào KB."

    def _is_chat_confirmation(self, message: str) -> bool:
        lowered = normalize_lookup(message)
        return lowered in {"confirm", "ok", "oke", "yes", "đồng ý", "duyệt", "chốt", "ghi vào kb", "lưu lại"} or any(
            marker in lowered for marker in ["confirm đi", "lưu vào kb", "ghi vào knowledge", "ghi lại đi"]
        )

    def _is_chat_cancel(self, message: str) -> bool:
        lowered = normalize_lookup(message)
        return lowered in {"cancel", "hủy", "huỷ", "bỏ qua", "reject", "cancel all"} or any(
            marker in lowered
            for marker in [
                "hủy session",
                "huỷ session",
                "đừng lưu",
                "cancel tất cả",
                "cancel het",
                "cancel hết",
                "hủy tất cả",
                "huỷ tất cả",
                "hủy hết",
                "huỷ hết",
                "xóa pending",
                "xoá pending",
                "clear pending",
            ]
        )

    def _is_pending_status_query(self, message: str) -> bool:
        lowered = normalize_lookup(message)
        has_pending = any(marker in lowered for marker in ["pending", "peding", "đang chờ", "chờ confirm", "chờ xác nhận"])
        if not has_pending:
            return False
        return any(
            marker in lowered
            for marker in [
                "có",
                "không",
                "ko",
                "nào",
                "list",
                "liệt kê",
                "show",
                "xem",
                "trạng thái",
                "status",
                "đang",
            ]
        )

    def _is_chat_summary_request(self, message: str) -> bool:
        lowered = normalize_lookup(message)
        return lowered in {"summary", "summarize", "tóm tắt", "tom tat"} or any(marker in lowered for marker in ["tóm tắt lại", "show draft", "xem draft"])

    def _search_knowledge_for_chat(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        records = self._approved_knowledge_records()
        exact = self._search_knowledge_deterministic(query, records=records)
        scored: dict[str, tuple[int, dict[str, Any]]] = {item["id"]: (100, item) for item in exact}
        query_terms = self._semantic_query_terms(query)
        query_phrases = self._semantic_query_phrases(query)
        query_acronyms = {normalize_lookup(item) for item in extract_acronyms(query)}

        for record in records:
            haystack = normalize_lookup(
                " ".join(
                    [
                        record.get("name", ""),
                        record.get("canonical_definition", ""),
                        record.get("logic", ""),
                        record.get("formula", "") or "",
                        " ".join(record.get("examples", [])),
                        " ".join(record.get("paraphrases", [])),
                        " ".join(record.get("conditions", [])),
                        record.get("domain", ""),
                    ]
                )
            )
            score = 0
            if normalize_lookup(record.get("name")) in query_acronyms:
                score += 80
            score += 12 * sum(1 for phrase in query_phrases if phrase in haystack)
            score += 4 * sum(1 for term in query_terms if self._contains_term(haystack, term))
            if score <= 0:
                continue
            existing_score = scored.get(record["id"], (0, record))[0]
            if score > existing_score:
                item = copy.deepcopy(record)
                item["_match_score"] = score
                scored[record["id"]] = (score, item)

        return [
            item
            for _score, item in sorted(scored.values(), key=lambda pair: (pair[0], pair[1].get("name", "")), reverse=True)[:limit]
        ]

    def _approved_knowledge_records(self) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(record)
            for record in self._load_knowledge_base()["knowledge"].values()
            if record.get("status") == "approved"
        ]

    def _search_knowledge_deterministic(self, query: str, *, records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        normalized_query = normalize_lookup(query)
        deterministic_records = []
        exact_acronym_records = []
        query_acronyms = extract_acronyms(query)
        for record in records or self._approved_knowledge_records():
            names = [record.get("name", ""), *record.get("paraphrases", [])]
            if query_acronyms and any(
                self._contains_term(name, acronym) for acronym in query_acronyms for name in names
            ):
                exact_acronym_records.append(record)
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
                deterministic_records.append(record)

        if query_acronyms and exact_acronym_records:
            return sorted(exact_acronym_records, key=lambda item: item.get("name", ""))
        return sorted(deterministic_records, key=lambda item: item.get("name", ""))

    def _semantic_query_terms(self, text: str) -> list[str]:
        stopwords = {
            "tôi",
            "mình",
            "muốn",
            "biết",
            "cho",
            "hỏi",
            "giúp",
            "giùm",
            "được",
            "gọi",
            "nào",
            "gì",
            "là",
            "cái",
            "này",
            "kia",
            "thì",
            "và",
            "hay",
            "hoặc",
            "với",
            "trong",
            "the",
            "what",
            "which",
            "called",
            "mean",
            "means",
            "want",
            "know",
        }
        words = re.findall(r"[A-Za-zÀ-ỹ_][\wÀ-ỹ_]{1,}", normalize_text(text))
        terms = [word for word in words if normalize_lookup(word) not in stopwords]
        return unique_values([*extract_acronyms(text), *terms])

    def _semantic_query_phrases(self, text: str) -> list[str]:
        terms = [normalize_lookup(term) for term in self._semantic_query_terms(text)]
        phrases = []
        for size in [3, 2]:
            for index in range(0, max(0, len(terms) - size + 1)):
                phrases.append(" ".join(terms[index : index + size]))
        return unique_values(phrases)

    def _synthesize_data_answer(self, message: str, data_result: dict[str, Any]) -> str:
        if data_result.get("status") in {"needs_dictionary", "needs_knowledge"}:
            return self._synthesize_data_answer_deterministic(data_result)
        if self._llm_configured():
            compact = {
                "status": data_result.get("status"),
                "question": data_result.get("question"),
                "sql": data_result.get("sql"),
                "missing": data_result.get("missing", []),
                "knowledge": [self._compact_knowledge(item) for item in data_result.get("known_knowledge", data_result.get("knowledge", []))],
                "dictionary": [self._compact_dictionary(item) for item in data_result.get("dictionary", [])],
                "examples": [self._compact_example(item) for item in data_result.get("examples", [])],
                "explanation": data_result.get("explanation", []),
            }
            system = (
                "You explain data-question results in natural Vietnamese. Use only the provided result. "
                "If status is needs_dictionary or needs_knowledge, clearly say what is missing. "
                "If SQL exists, explain it is a draft and mention key assumptions."
            )
            answer = self.llm_client.complete_text(
                system=system,
                user=json.dumps({"message": message, "result": compact}, ensure_ascii=False),
                temperature=0.2,
            )
            if answer:
                return answer
        return self._synthesize_data_answer_deterministic(data_result)

    def _synthesize_data_answer_deterministic(self, data_result: dict[str, Any]) -> str:
        status = data_result.get("status")
        if status == "sql_draft":
            explanation = " ".join(data_result.get("explanation", [])[:3])
            return f"Mình đã có đủ context để tạo SQL draft. {explanation}".strip()
        if status == "needs_dictionary":
            missing = data_result.get("missing", [])
            rendered = "; ".join(item.get("question", "") for item in missing[:5])
            return f"Mình hiểu ý câu hỏi, nhưng chưa đủ mapping bảng/cột để sinh SQL an toàn. Cần bổ sung: {rendered}"
        if status == "needs_knowledge":
            missing = data_result.get("missing", [])
            rendered = "; ".join(item.get("question", "") for item in missing[:5])
            return f"Mình chưa đủ Domain Knowledge để hiểu chắc câu hỏi này. Cần làm rõ: {rendered}"
        return data_result.get("answer", "Mình cần thêm context để trả lời chắc chắn.")

    def _build_dictionary_help_answer(self, message: str, context: dict[str, Any]) -> str:
        if context.get("dictionary"):
            tables = ", ".join(item.get("table", "") for item in context["dictionary"][:5])
            return f"Mình tìm thấy các mapping liên quan: {tables}. Bạn có thể hỏi tiếp theo tên bảng/cột hoặc alias nghiệp vụ."
        return (
            "Hiện chưa có data dictionary phù hợp với câu hỏi này. "
            "Bạn có thể thêm bằng action `add_data_dictionary` với table, description, columns, relationships và owner."
        )

    def _build_llm_sql_draft(
        self,
        question: str,
        known: list[dict[str, Any]],
        dictionary: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self._llm_configured():
            return {}
        compact = {
            "question": question,
            "knowledge": [self._compact_knowledge(item) for item in known],
            "dictionary": [self._compact_dictionary(item) for item in dictionary],
        }
        system = (
            "You draft SQL for business data questions. Return only JSON with fields: sql, explanation, answer. "
            "Use only tables and columns present in the provided dictionary. Do not invent tables or columns. "
            "If context is insufficient, return an empty sql string and explain what is missing."
        )
        parsed = self.llm_client.complete_json(
            system=system,
            user=json.dumps(compact, ensure_ascii=False),
            temperature=0,
        )
        if not isinstance(parsed, dict):
            return {}
        sql = normalize_text(parsed.get("sql"))
        if not sql:
            return {}
        allowed_tables = {normalize_lookup(item.get("table")) for item in dictionary}
        if not any(table and table in normalize_lookup(sql) for table in allowed_tables):
            return {}
        explanation = parsed.get("explanation")
        if isinstance(explanation, str):
            explanation = [explanation]
        if not isinstance(explanation, list):
            explanation = ["SQL draft do LLM tạo từ Data Dictionary đã retrieve."]
        return {
            "sql": sql,
            "explanation": [normalize_text(item) for item in explanation if normalize_text(item)],
            "answer": normalize_text(parsed.get("answer")),
        }

    def _compact_knowledge(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "definition": item.get("canonical_definition", ""),
            "logic": item.get("logic", ""),
            "formula": item.get("formula"),
            "conditions": item.get("conditions", []),
            "paraphrases": item.get("paraphrases", []),
            "domain": item.get("domain", ""),
        }

    def _compact_dictionary(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id", ""),
            "table": item.get("table", ""),
            "description": item.get("description", ""),
            "columns": item.get("columns", []),
            "relationships": item.get("relationships", []),
        }

    def _compact_example(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id", ""),
            "question": item.get("question", ""),
            "sql": item.get("sql", ""),
            "explanation": item.get("explanation", ""),
            "concepts": item.get("concepts", []),
            "used_tables": item.get("used_tables", []),
        }

    def _compact_planner_knowledge(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "definition": item.get("canonical_definition", ""),
            "formula": item.get("formula"),
            "domain": item.get("domain", ""),
        }

    def _compact_planner_dictionary(self, item: dict[str, Any]) -> dict[str, Any]:
        compact_columns = []
        for column in item.get("columns", [])[:24]:
            if not isinstance(column, dict):
                continue
            compact_columns.append(
                {
                    "name": column.get("name", ""),
                    "data_type": column.get("data_type", ""),
                    "business_meaning": column.get("business_meaning", ""),
                    "aliases": column.get("aliases", []),
                }
            )
        return {
            "id": item.get("id", ""),
            "table": item.get("table", ""),
            "description": item.get("description", ""),
            "columns": compact_columns,
        }

    def _compact_planner_example(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id", ""),
            "question": item.get("question", ""),
            "explanation": item.get("explanation", ""),
            "concepts": item.get("concepts", []),
            "used_tables": item.get("used_tables", []),
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

    def _search_dictionary_for_question(
        self,
        question: str,
        known: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records_by_id: dict[str, dict[str, Any]] = {}
        queries = [question]
        for item in known:
            queries.extend(
                [
                    item.get("name", ""),
                    item.get("canonical_definition", ""),
                    item.get("formula", "") or "",
                    " ".join(item.get("paraphrases", [])),
                    " ".join(item.get("conditions", [])),
                ]
            )
        for query in queries:
            for record in self.search_data_dictionary(query):
                records_by_id[record["id"]] = record
        return sorted(records_by_id.values(), key=lambda item: item.get("table", ""))

    def _search_dictionary_for_chat(
        self,
        question: str,
        known: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records_by_id: dict[str, tuple[int, dict[str, Any]]] = {}
        queries = [question]
        for item in known:
            queries.extend(
                [
                    item.get("name", ""),
                    item.get("canonical_definition", ""),
                    item.get("formula", "") or "",
                    " ".join(item.get("paraphrases", [])),
                    " ".join(item.get("conditions", [])),
                ]
            )
        query_terms = []
        for query in queries:
            query_terms.extend(self._extract_question_terms(query))

        for record in self._load_data_dictionary()["records"].values():
            if record.get("status") != "approved":
                continue
            score = 0
            haystack = self._dictionary_haystack(record)
            normalized_haystack = normalize_lookup(haystack)
            for query in queries:
                normalized_query = normalize_lookup(query)
                if normalized_query and normalized_query in normalized_haystack:
                    score += 12
            score += 3 * sum(1 for term in query_terms if self._dictionary_matches_term(record, term))
            if score <= 0:
                continue
            item = copy.deepcopy(record)
            item["_match_score"] = score
            existing_score = records_by_id.get(item["id"], (0, item))[0]
            if score > existing_score:
                records_by_id[item["id"]] = (score, item)
        return [
            item
            for _score, item in sorted(records_by_id.values(), key=lambda pair: (pair[0], pair[1].get("table", "")), reverse=True)
        ]

    def _dictionary_covers_term(self, dictionary: list[dict[str, Any]], term: str) -> bool:
        return any(self._dictionary_matches_term(record, term) for record in dictionary)

    def _dictionary_covers_knowledge(self, knowledge: dict[str, Any], dictionary: list[dict[str, Any]]) -> bool:
        if not dictionary:
            return False
        name = knowledge.get("name", "")
        if self._dictionary_covers_term(dictionary, name):
            return True

        context = " ".join(
            [
                knowledge.get("canonical_definition", ""),
                knowledge.get("formula", "") or "",
                " ".join(knowledge.get("paraphrases", [])),
                " ".join(knowledge.get("conditions", [])),
            ]
        )
        context_terms = [
            term
            for term in self._extract_question_terms(context)
            if normalize_lookup(term) != normalize_lookup(name) and not self._is_ignorable_question_term(term)
        ]
        if not context_terms:
            return False
        covered = [term for term in context_terms if self._dictionary_covers_term(dictionary, term)]
        if self._looks_like_ratio_metric(knowledge):
            has_revenue = any(self._is_revenue_term(term) for term in covered)
            has_user = any(self._is_user_term(term) for term in covered)
            return has_revenue and has_user
        return bool(covered)

    def _is_ignorable_question_term(self, term: str) -> bool:
        cleaned = normalize_lookup(term).strip("_ ")
        if not cleaned:
            return True
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
            "total",
            "average",
            "avg",
            "trung",
            "bình",
            "kỳ",
            "chắc",
            "nhé",
            "lấy",
            "thôi",
            "một",
            "vài",
            "số",
            "được",
            "không",
            "giúp",
            "mình",
            "tôi",
            "period",
            "reporting",
        }
        return cleaned in stopwords or cleaned.isdigit()

    def _is_revenue_term(self, term: str) -> bool:
        cleaned = normalize_lookup(term)
        return any(marker in cleaned for marker in ["revenue", "doanh thu", "gmv", "amount", "payment"])

    def _is_user_term(self, term: str) -> bool:
        cleaned = normalize_lookup(term)
        return any(marker in cleaned for marker in ["user", "người dùng", "khách hàng", "customer"])

    def _looks_like_ratio_metric(self, knowledge: dict[str, Any]) -> bool:
        context = normalize_lookup(
            " ".join(
                [
                    knowledge.get("name", ""),
                    knowledge.get("canonical_definition", ""),
                    knowledge.get("formula", "") or "",
                    " ".join(knowledge.get("paraphrases", [])),
                ]
            )
        )
        return "/" in context or " per " in f" {context} " or ("revenue" in context and "user" in context)

    def _find_dictionary_columns_for_term(
        self,
        dictionary: list[dict[str, Any]],
        term: str,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        matches: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        normalized_term = normalize_lookup(term)
        for record in dictionary:
            for column in record.get("columns", []):
                haystack = " ".join(
                    [
                        column.get("name", ""),
                        column.get("business_meaning", ""),
                        column.get("data_type", ""),
                        " ".join(column.get("aliases", [])),
                    ]
                )
                if self._contains_term(haystack, term):
                    column_name = normalize_lookup(column.get("name"))
                    aliases = {normalize_lookup(alias) for alias in column.get("aliases", [])}
                    score = 5
                    if column_name == normalized_term:
                        score = 0
                    elif normalized_term in aliases and any(marker in column_name for marker in ["name", "title", "label"]):
                        score = 1
                    elif normalized_term in aliases:
                        score = 2
                    elif any(marker in column_name for marker in ["name", "title", "label"]):
                        score = 3
                    if column_name.endswith("_id") or column_name == "id":
                        score += 4
                    matches.append((score, record, column))
        return [(record, column) for _score, record, column in sorted(matches, key=lambda item: item[0])]

    def _find_first_column_for_terms(
        self,
        dictionary: list[dict[str, Any]],
        terms: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        for term in terms:
            matches = self._find_dictionary_columns_for_term(dictionary, term)
            if matches:
                return matches[0]
        return None

    def _sql_identifier(self, value: str) -> str:
        cleaned = normalize_text(value)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cleaned):
            return cleaned
        return '"' + cleaned.replace('"', '""') + '"'

    def _sql_column_ref(self, table: str, column: str) -> str:
        return f"{self._sql_identifier(table)}.{self._sql_identifier(column)}"

    def _sql_path_ref(self, value: str) -> str:
        parts = [part for part in normalize_text(value).split(".") if part]
        return ".".join(self._sql_identifier(part) for part in parts)

    def _build_from_clause(self, dictionary: list[dict[str, Any]]) -> str:
        tables = unique_values([record.get("table", "") for record in dictionary])
        if not tables:
            return ""
        joined = {tables[0]}
        clauses = [f"FROM {self._sql_identifier(tables[0])}"]
        relationships = []
        for record in dictionary:
            relationships.extend(record.get("relationships", []))

        for table in tables[1:]:
            join_clause = ""
            for relationship in relationships:
                from_path = normalize_text(relationship.get("from"))
                to_path = normalize_text(relationship.get("to"))
                from_table = from_path.split(".")[0] if "." in from_path else ""
                to_table = to_path.split(".")[0] if "." in to_path else ""
                if table == from_table and to_table in joined:
                    join_clause = f"JOIN {self._sql_identifier(table)} ON {self._sql_path_ref(from_path)} = {self._sql_path_ref(to_path)}"
                    break
                if table == to_table and from_table in joined:
                    join_clause = f"JOIN {self._sql_identifier(table)} ON {self._sql_path_ref(from_path)} = {self._sql_path_ref(to_path)}"
                    break
            if join_clause:
                clauses.append(join_clause)
                joined.add(table)
        return "\n".join(clauses)

    def _build_deterministic_sql_draft(
        self,
        question: str,
        known: list[dict[str, Any]],
        dictionary: list[dict[str, Any]],
        detected_concepts: list[str],
    ) -> str:
        from_clause = self._build_from_clause(dictionary)
        if not from_clause:
            return ""

        known_names = {normalize_lookup(item.get("name")) for item in known}
        group_columns: list[tuple[str, str]] = []
        for concept in detected_concepts:
            if normalize_lookup(concept) in known_names or self._is_ignorable_question_term(concept):
                continue
            matches = self._find_dictionary_columns_for_term(dictionary, concept)
            if matches:
                record, column = matches[0]
                ref = self._sql_column_ref(record["table"], column["name"])
                alias = self._sql_identifier(column["name"])
                if (ref, alias) not in group_columns:
                    group_columns.append((ref, alias))

        metric_expressions: list[tuple[str, str]] = []
        for item in known:
            metric_name = item.get("name", "metric").lower()
            direct_column = self._find_first_column_for_terms(dictionary, [item.get("name", "")])
            if direct_column:
                record, column = direct_column
                metric_expressions.append((self._sql_column_ref(record["table"], column["name"]), metric_name))
                continue

            if self._looks_like_ratio_metric(item):
                revenue_column = self._find_first_column_for_terms(dictionary, ["revenue", "doanh thu", "gmv", "amount"])
                user_column = self._find_first_column_for_terms(dictionary, ["active user", "user", "user_id", "customer"])
                if revenue_column and user_column:
                    revenue_record, revenue = revenue_column
                    user_record, user = user_column
                    expression = (
                        f"SUM({self._sql_column_ref(revenue_record['table'], revenue['name'])}) / "
                        f"NULLIF(COUNT(DISTINCT {self._sql_column_ref(user_record['table'], user['name'])}), 0)"
                    )
                    metric_expressions.append((expression, metric_name))

        if not metric_expressions:
            revenue_column = self._find_first_column_for_terms(dictionary, ["revenue", "doanh thu", "gmv", "amount"])
            if revenue_column and any(self._is_revenue_term(term) for term in self._extract_question_terms(question)):
                record, column = revenue_column
                metric_expressions.append((f"SUM({self._sql_column_ref(record['table'], column['name'])})", "revenue"))

        select_parts = [f"{ref} AS {alias}" for ref, alias in group_columns]
        select_parts.extend(f"{expr} AS {self._sql_identifier(alias)}" for expr, alias in metric_expressions)
        if not select_parts:
            first_record = dictionary[0]
            for column in first_record.get("columns", [])[:5]:
                select_parts.append(
                    f"{self._sql_column_ref(first_record['table'], column['name'])} AS {self._sql_identifier(column['name'])}"
                )
        if not select_parts:
            return ""

        sql = "SELECT\n  " + ",\n  ".join(select_parts) + "\n" + from_clause
        if group_columns and metric_expressions:
            sql += "\nGROUP BY " + ", ".join(ref for ref, _alias in group_columns)
        if not metric_expressions:
            sql += "\nLIMIT 100"
        return sql + ";"

    def _extract_question_terms(self, text: str) -> list[str]:
        cleaned = normalize_text(text)
        terms = extract_acronyms(cleaned)
        for match in re.finditer(r"(?:theo|by|group by|phân theo)\s+([A-Za-zÀ-ỹ_][\wÀ-ỹ_ ]{1,40})", cleaned, flags=re.IGNORECASE):
            grouped_term = re.split(
                r"\s+(?:là|bao|how|what|where|when|is|are)\b",
                match.group(1).strip(" ?.,"),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            terms.append(grouped_term.strip(" ?.,"))
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
        dictionary: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        dictionary = dictionary or []
        missing: list[dict[str, str]] = []
        known_names = {normalize_lookup(item.get("name")) for item in known}
        for item in known:
            term = item.get("name", "")
            if term and not self._dictionary_covers_knowledge(item, dictionary):
                missing.append(
                    {
                        "type": "table_mapping",
                        "concept": term,
                        "question": f"{term} lấy từ bảng/cột nào hoặc được tính từ những cột nào?",
                    }
                )

        for concept in detected_concepts:
            if normalize_lookup(concept) in known_names or self._is_ignorable_question_term(concept):
                continue
            if not self._dictionary_covers_term(dictionary, concept):
                missing.append(
                    {
                        "type": "column_mapping",
                        "concept": concept,
                        "question": f"{concept} nằm ở bảng/cột nào?",
                    }
                )

        if not known and not missing and not dictionary:
            for term in unique_values(detected_concepts or [question]):
                if not self._is_ignorable_question_term(term):
                    missing.append(
                        {
                            "type": "column_mapping",
                            "concept": term,
                            "question": f"{term} nằm ở bảng/cột nào?",
                        }
                    )

        seen: set[tuple[str, str]] = set()
        deduped = []
        for item in missing:
            key = (item["type"], normalize_lookup(item["concept"]))
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

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
        elif example:
            explanation.append(f"SQL draft lấy từ Question Example {example.get('id')}")
        else:
            explanation.append("SQL draft được dựng từ Data Dictionary đã approved, không dùng bảng/cột ngoài context retrieved.")
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

    def _load_chat_sessions(self) -> dict[str, Any]:
        if self.db:
            return self.db.load_chat_sessions()
        return self._load_json(self.chat_sessions_path, empty_chat_sessions)

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
            if path == self.chat_sessions_path:
                self.db.save_chat_sessions(data)
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
