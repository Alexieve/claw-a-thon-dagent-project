from __future__ import annotations

import json
import os
import threading
from typing import Any
from urllib import error, request

try:
    import httpx
except ImportError:  # pragma: no cover - fallback to urllib khi httpx vắng mặt
    httpx = None


# Lỗi coi như "không có kết quả" -> trả "" để caller fallback.
_HTTP_ERRORS: tuple[type[Exception], ...] = (
    error.URLError,
    TimeoutError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    json.JSONDecodeError,
)
if httpx is not None:
    _HTTP_ERRORS = _HTTP_ERRORS + (httpx.HTTPError,)

# Client dùng chung ở mức module để tái dùng kết nối (keep-alive), tránh TCP+TLS handshake
# mỗi lần gọi LLM. Tạo lazy, thread-safe; chia sẻ qua các worker thread của runtime.
_HTTP_CLIENT: "httpx.Client | None" = None
_HTTP_CLIENT_LOCK = threading.Lock()


def _get_http_client(timeout: float):
    if httpx is None:
        return None
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        with _HTTP_CLIENT_LOCK:
            if _HTTP_CLIENT is None:
                _HTTP_CLIENT = httpx.Client(
                    timeout=timeout,
                    limits=httpx.Limits(
                        max_keepalive_connections=10,
                        max_connections=20,
                        keepalive_expiry=60.0,
                    ),
                )
    return _HTTP_CLIENT


class AgentLLMClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "")
        try:
            self.timeout = float(os.getenv("LLM_TIMEOUT") or "30")
        except ValueError:
            self.timeout = 30.0

    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0,
        model: str | None = None,
    ) -> dict[str, Any] | None:
        raw = self._complete(
            system=system,
            user=user,
            temperature=temperature,
            response_format={"type": "json_object"},
            model=model,
        )
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> str:
        return self._complete(system=system, user=user, temperature=temperature, model=model) or ""

    def _complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> str:
        if not self.configured():
            return ""
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        client = _get_http_client(self.timeout)
        try:
            if client is not None:
                resp = client.post(url, json=payload, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
            else:
                req = request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with request.urlopen(req, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
        except _HTTP_ERRORS:
            return ""
        # GIU xuong dong cua noi dung LLM (markdown bang/list/code can \n de render dung tren FE);
        # truoc day normalize_text flatten het \n -> answer thanh mot dong. Caller text dung
        # _sanitize_user_answer/normalize_markdown_text de don whitespace, caller json dung
        # json.loads (newline trong JSON vo hai). Chi strip dau/cuoi o day.
        return content.strip() if isinstance(content, str) else ""
