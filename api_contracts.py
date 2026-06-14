from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol


PUBLIC_FE_ACTIONS = {"chat", "search_knowledge", "storage_status", "list_chat_sessions", "get_chat_history"}


class RequestContextLike(Protocol):
    user_id: str | None
    session_id: str | None


class StoreLike(Protocol):
    def chat(
        self,
        *,
        message: str,
        user_id: str = "",
        session_id: str = "",
        pending_action_id: str = "",
        debug_context: bool = False,
        use_runtime_skills: Any = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    public_for_fe: bool
    handler: Callable[[dict[str, Any], RequestContextLike], dict[str, Any]]


class AgentApiRouter:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.actions: dict[str, ActionSpec] = {}
        self._register_actions()

    def dispatch(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        request_id = self._text(payload.get("request_id"))
        action = self._resolve_action(payload)

        try:
            spec = self.actions.get(action)
            if spec is None:
                return self._error(
                    code="unknown_action",
                    message=f"Action chua duoc ho tro: {action}",
                    context=context,
                    request_id=request_id,
                    details={"action": action, "help": self.build_help()},
                )

            result = spec.handler(payload, context)
            if action == "chat":
                result = normalize_chat_result(result)
            return self._success(result=result, context=context, request_id=request_id)
        except ValueError as error:
            return self._error(
                code="validation_error",
                message=str(error),
                context=context,
                request_id=request_id,
            )

    def build_help(self) -> dict[str, Any]:
        return {
            "agent": "business-knowledge-learning-agent",
            "purpose": "Thu thap, parse, review, va chuan hoa knowledge nghiep vu tu stakeholder va file text.",
            "contract_version": "v2",
            "public_fe_actions": sorted(PUBLIC_FE_ACTIONS),
            "actions": {
                name: {
                    "description": spec.description,
                    "public_for_fe": spec.public_for_fe,
                }
                for name, spec in sorted(self.actions.items())
            },
        }

    def _register_actions(self) -> None:
        self._register("help", "Hien thi action duoc ho tro.", False, lambda payload, context: self.build_help())
        self._register("chat", "Entry chinh cho hoi dap freeform va confirm workflow.", True, self._chat)
        self._register("teach_text", "Day knowledge da duoc user confirm.", False, self._teach_text)
        self._register("start_teach_session", "Bat dau Flow A teaching nhieu luot.", False, self._start_teach_session)
        self._register("append_teach_message", "Them message vao teaching session.", False, self._append_teach_message)
        self._register("summarize_teach_session", "Tom tat draft knowledge de user confirm.", False, self._summarize_teach_session)
        self._register("confirm_teach_session", "Confirm/cancel teaching session.", False, self._confirm_teach_session)
        self._register("review_candidate", "Approve/reject pending change.", False, self._review_candidate)
        self._register("list_candidates", "Liet ke candidate theo status.", False, self._list_candidates)
        self._register("search_knowledge", "Tim approved knowledge.", True, self._search_knowledge)
        self._register("ask_data_question", "Hoi cau hoi data va sinh missing context hoac SQL draft.", False, self._ask_data_question)
        self._register("add_data_dictionary", "Them mapping bang/cot da approved.", False, self._add_data_dictionary)
        self._register("search_data_dictionary", "Tim mapping bang/cot.", False, self._search_data_dictionary)
        self._register("list_data_dictionary", "Liet ke data dictionary da luu.", False, self._list_data_dictionary)
        self._register("add_question_example", "Them SQL mau da approved.", False, self._add_question_example)
        self._register("search_question_examples", "Tim SQL mau.", False, self._search_question_examples)
        self._register("list_question_examples", "Liet ke question examples da luu.", False, self._list_question_examples)
        self._register("storage_status", "Kiem tra storage backend.", True, self._storage_status)
        self._register("list_chat_sessions", "Lay danh sach chat session theo user_id.", True, self._list_chat_sessions)
        self._register("get_chat_history", "Lay lich su chat day du theo session_id.", True, self._get_chat_history)
        self._register("analyze_text", "Phan tich text dua tren knowledge da co.", False, self._analyze_text)
        self._register("ingest_document", "Ingest noi dung file dang text.", False, self._ingest_document)

    def _register(
        self,
        name: str,
        description: str,
        public_for_fe: bool,
        handler: Callable[[dict[str, Any], RequestContextLike], dict[str, Any]],
    ) -> None:
        self.actions[name] = ActionSpec(
            name=name,
            description=description,
            public_for_fe=public_for_fe,
            handler=handler,
        )

    def _resolve_action(self, payload: dict[str, Any]) -> str:
        action = self._text(payload.get("action"))
        if action:
            return action.lower()
        if payload.get("message") or payload.get("question"):
            return "chat"
        return "help"

    def _chat(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return self.store.chat(
            message=self._text(payload.get("message") or payload.get("question")),
            user_id=self._text(payload.get("user_id") or self._context_value(context, "user_id")),
            session_id=self._text(payload.get("session_id") or self._context_value(context, "session_id")),
            pending_action_id=self._text(payload.get("pending_action_id")),
            debug_context=bool(payload.get("debug_context")),
            use_runtime_skills=payload.get("use_runtime_skills"),
        )

    def _teach_text(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        result = self.store.teach_text(
            text=self._text(payload.get("text") or payload.get("message")),
            stakeholder=self._text(payload.get("stakeholder")),
            team=self._text(payload.get("team")),
            domain=self._text(payload.get("domain")),
            owner=self._text(payload.get("owner")),
        )
        result["answer"] = (
            f"Da tao {len(result['knowledge_created'])} knowledge moi va {len(result['change_requests'])} pending change."
            if result["knowledge_created"] or result["change_requests"]
            else "Da luu raw event nhung chua parse duoc knowledge ro rang."
        )
        return result

    def _start_teach_session(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return self.store.start_teach_session(
            message=self._text(payload.get("message") or payload.get("text")),
            stakeholder=self._text(payload.get("stakeholder")),
            team=self._text(payload.get("team")),
            domain=self._text(payload.get("domain")),
            owner=self._text(payload.get("owner")),
        )

    def _append_teach_message(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return self.store.append_teach_message(
            session_id=self._text(payload.get("session_id")),
            message=self._text(payload.get("message") or payload.get("text")),
        )

    def _summarize_teach_session(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return self.store.summarize_teach_session(session_id=self._text(payload.get("session_id")))

    def _confirm_teach_session(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        result = self.store.confirm_teach_session(
            session_id=self._text(payload.get("session_id")),
            decision=self._text(payload.get("decision")) or "confirm",
        )
        result["answer"] = (
            f"Da ghi {len(result['knowledge_created'])} knowledge moi vao KB."
            if result.get("knowledge_created")
            else f"Da tao {len(result.get('change_requests', []))} pending change can duyet."
            if result.get("change_requests")
            else "Teaching session da duoc huy."
        )
        return result

    def _review_candidate(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        updates = payload.get("updates")
        result = self.store.review_candidate(
            candidate_id=self._text(payload.get("candidate_id")),
            decision=self._text(payload.get("decision")),
            updates=updates if isinstance(updates, dict) else None,
        )
        result["answer"] = (
            "Candidate da duoc duyet vao knowledge base."
            if result.get("knowledge")
            else f"Candidate dang o trang thai {result['candidate']['status']}."
        )
        return result

    def _list_candidates(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return {"candidates": self.store.list_candidates(status=self._text(payload.get("status")))}

    def _search_knowledge(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return {"knowledge": self.store.search_knowledge(query=self._text(payload.get("query")))}

    def _ask_data_question(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return self.store.ask_data_question(question=self._text(payload.get("question") or payload.get("message")))

    def _add_data_dictionary(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        columns = payload.get("columns")
        relationships = payload.get("relationships")
        result = {
            "data_dictionary": self.store.add_data_dictionary(
                table=self._text(payload.get("table")),
                description=self._text(payload.get("description")),
                columns=columns if isinstance(columns, list) else [],
                relationships=relationships if isinstance(relationships, list) else [],
                owner=self._text(payload.get("owner")),
                status=self._text(payload.get("status")) or "approved",
            )
        }
        result["answer"] = f"Da them data dictionary cho bang {result['data_dictionary']['table']}."
        return result

    def _search_data_dictionary(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return {"data_dictionary": self.store.search_data_dictionary(query=self._text(payload.get("query")))}

    def _list_data_dictionary(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return {"data_dictionary": self.store.list_data_dictionary()}

    def _add_question_example(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        concepts = payload.get("concepts")
        used_tables = payload.get("used_tables")
        result = {
            "question_example": self.store.add_question_example(
                question=self._text(payload.get("question")),
                sql=self._text(payload.get("sql")),
                explanation=self._text(payload.get("explanation")),
                concepts=concepts if isinstance(concepts, list) else [],
                used_tables=used_tables if isinstance(used_tables, list) else [],
                owner=self._text(payload.get("owner")),
                status=self._text(payload.get("status")) or "approved",
            )
        }
        result["answer"] = f"Da them question example {result['question_example']['id']}."
        return result

    def _search_question_examples(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return {"question_examples": self.store.search_question_examples(query=self._text(payload.get("query")))}

    def _list_question_examples(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return {"question_examples": self.store.list_question_examples()}

    def _storage_status(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        return self.store.storage_status()

    def _list_chat_sessions(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        user_id = self._text(payload.get("user_id") or self._context_value(context, "user_id"))
        return {"sessions": self.store.list_chat_sessions_by_user(user_id=user_id)}

    def _get_chat_history(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        session_id = self._text(payload.get("session_id") or self._context_value(context, "session_id"))
        return self.store.get_chat_history(session_id=session_id)

    def _analyze_text(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        analysis = self.store.analyze_text(self._text(payload.get("text") or payload.get("message")))
        return {"answer": build_analyze_answer(analysis), **analysis}

    def _ingest_document(self, payload: dict[str, Any], context: RequestContextLike) -> dict[str, Any]:
        result = self.store.ingest_document(
            text=self._text(payload.get("text") or payload.get("content")),
            title=self._text(payload.get("title")),
            stakeholder=self._text(payload.get("stakeholder")),
            team=self._text(payload.get("team")),
            domain=self._text(payload.get("domain")),
            owner=self._text(payload.get("owner")),
        )
        result["answer"] = f"Da ingest {len(result['chunks'])} chunk va tao {len(result['candidates'])} candidate can review."
        return result

    def _success(self, *, result: dict[str, Any], context: RequestContextLike, request_id: str = "") -> dict[str, Any]:
        response = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "session_id": self._context_value(context, "session_id") or result.get("chat_session_id") or result.get("session_id"),
            "result": result,
        }
        if request_id:
            response["request_id"] = request_id
        return response

    def _error(
        self,
        *,
        code: str,
        message: str,
        context: RequestContextLike,
        request_id: str = "",
        details: Any = None,
    ) -> dict[str, Any]:
        error = {"code": code, "message": message}
        if details is not None:
            error["details"] = details
        response = {
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "session_id": self._context_value(context, "session_id") or None,
            "error": error,
        }
        if request_id:
            response["request_id"] = request_id
        return response

    def _context_value(self, context: RequestContextLike, name: str) -> str:
        return self._text(getattr(context, name, ""))

    def _text(self, value: Any) -> str:
        return str(value or "").strip()


def normalize_chat_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    normalized.setdefault("status", "answered")
    normalized.setdefault("intent", "")
    normalized.setdefault("answer", "")
    normalized.setdefault("question", "")
    normalized.setdefault("chat_session_id", normalized.get("session_id", ""))
    normalized.setdefault("requires_confirmation", False)
    normalized.setdefault("pending_action_id", "")
    normalized.setdefault("pending_action_type", "")
    normalized.setdefault("confirm_options", ["confirm", "cancel"] if normalized.get("pending_action_id") else [])
    normalized.setdefault("session_state", "idle")
    normalized.setdefault("resolved_question", normalized.get("question", ""))
    normalized.setdefault("conversation_context_used", False)
    normalized.setdefault("context_terms", [])
    normalized.setdefault("context_backend", "")
    normalized.setdefault("missing", [])
    normalized.setdefault("used_knowledge_ids", [])
    normalized.setdefault("used_dictionary_ids", [])
    normalized.setdefault("used_example_ids", [])
    normalized.setdefault("debug", {})

    pending_action_id = str(normalized.get("pending_action_id") or "")
    pending_action_type = str(normalized.get("pending_action_type") or "")
    normalized["pending_action"] = {
        "id": pending_action_id,
        "type": pending_action_type,
        "status": "pending" if pending_action_id else "",
        "confirm_options": normalized.get("confirm_options", []),
    }
    if pending_action_id:
        normalized["requires_confirmation"] = bool(normalized.get("requires_confirmation", False))
        normalized["confirm_options"] = normalized.get("confirm_options") or ["confirm", "cancel"]
        normalized["pending_action"]["confirm_options"] = normalized["confirm_options"]
    return normalized


def build_analyze_answer(result: dict[str, Any]) -> str:
    parts: list[str] = []
    if result["known"]:
        rendered = "; ".join(
            f"{item['name']}: {item.get('canonical_definition') or 'Da co trong knowledge base'}"
            for item in result["known"]
        )
        parts.append(f"Da biet: {rendered}.")
    if result["pending"]:
        parts.append("Dang cho duyet: " + ", ".join(item["name"] for item in result["pending"]) + ".")
    if result["conflicts"]:
        parts.append("Dang mau thuan: " + ", ".join(item["name"] for item in result["conflicts"]) + ".")
    if result["unknown"]:
        parts.append("Chua co knowledge chuan: " + ", ".join(result["unknown"]) + ".")
    return " ".join(parts) if parts else "Khong phat hien knowledge lien quan."
