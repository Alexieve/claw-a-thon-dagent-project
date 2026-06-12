from __future__ import annotations

from typing import Any

try:
    from greennode_agentbase.memory import MemoryClient
    from greennode_agentbase.memory.models import EventCreateRequest, EventPayload
except ImportError:  # pragma: no cover - optional dependency for tests/system python
    MemoryClient = None
    EventCreateRequest = None
    EventPayload = None

from .utils import normalize_text, now_iso


class SessionContextStoreError(RuntimeError):
    pass

class LocalChatSessionEventStore:
    backend_name = "local"

    def append_event(
        self,
        *,
        chat_session: dict[str, Any],
        user_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        if normalize_text(role) == "assistant":
            chat_session.setdefault("messages", [])
            chat_session["messages"].append({"role": "assistant", "content": normalize_text(content), "created_at": now_iso()})
            chat_session["messages"] = chat_session["messages"][-20:]

    def list_recent_events(
        self,
        *,
        chat_session: dict[str, Any],
        user_id: str,
        session_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        messages = chat_session.get("messages", []) if isinstance(chat_session.get("messages"), list) else []
        return [
            {
                "role": normalize_text(message.get("role")),
                "content": normalize_text(message.get("content")),
                "created_at": normalize_text(message.get("created_at")),
            }
            for message in messages[-limit:]
            if normalize_text(message.get("content"))
        ]


class AgentBaseMemoryEventStore:
    backend_name = "agentbase"

    def __init__(self, *, memory_id: str) -> None:
        self.memory_id = normalize_text(memory_id)
        self.client = MemoryClient() if MemoryClient is not None and self.memory_id else None

    def append_event(
        self,
        *,
        chat_session: dict[str, Any],
        user_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        if not self.client or not EventCreateRequest or not EventPayload:
            raise SessionContextStoreError("AgentBase Memory SDK chưa sẵn sàng.")
        if not normalize_text(user_id) or not normalize_text(session_id):
            raise SessionContextStoreError("Thiếu user_id hoặc session_id để ghi AgentBase Memory event.")
        payload = EventPayload(type="conversational", role=normalize_text(role), message=normalize_text(content))
        self.client.create_event(
            id=self.memory_id,
            actorId=normalize_text(user_id),
            sessionId=normalize_text(session_id),
            request=EventCreateRequest(payload=payload),
        )

    def list_recent_events(
        self,
        *,
        chat_session: dict[str, Any],
        user_id: str,
        session_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.client:
            raise SessionContextStoreError("AgentBase Memory SDK chưa sẵn sàng.")
        result = self.client.list_events(
            id=self.memory_id,
            actorId=normalize_text(user_id),
            sessionId=normalize_text(session_id),
            page=1,
            size=max(1, limit),
        )
        items = getattr(result, "list_data", None) or getattr(result, "listData", None) or []
        events = []
        for item in reversed(items):
            payload = getattr(item, "payload", None)
            message = normalize_text(getattr(payload, "message", "") if payload else "")
            if not message:
                continue
            events.append(
                {
                    "role": normalize_text(getattr(payload, "role", "") if payload else ""),
                    "content": message,
                    "created_at": normalize_text(getattr(item, "event_timestamp", "") or getattr(item, "eventTimestamp", "")),
                }
            )
        return events[-limit:]
