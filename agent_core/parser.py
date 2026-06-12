from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib import error, request

from .utils import (
    candidate_template,
    extract_acronyms,
    normalize_confidence,
    normalize_text,
    split_sentences,
    unique_values,
)


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
