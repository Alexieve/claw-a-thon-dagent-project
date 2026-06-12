from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

from .utils import normalize_text


class AgentLLMClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "")

    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0,
    ) -> dict[str, Any] | None:
        raw = self._complete(system=system, user=user, temperature=temperature, response_format={"type": "json_object"})
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
    ) -> str:
        return self._complete(system=system, user=user, temperature=temperature) or ""

    def _complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if not self.configured():
            return ""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
        except (error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            return ""
        return normalize_text(content)
