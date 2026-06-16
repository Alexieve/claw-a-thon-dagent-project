from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .constants import ACRONYM_PATTERN, ALLOWED_CANDIDATE_STATUSES, ALLOWED_KINDS


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_markdown_text(value: Any) -> str:
    """Chuan hoa text markdown cho FE nhung GIU xuong dong.

    Khac normalize_text (flatten moi whitespace ve mot dong, lam vo bang/list/code
    block khi hien thi tren FE): ham nay chi
      - quy CRLF/CR ve LF,
      - bo khoang trang thua o CUOI moi dong (giu thut dau dong cho code block),
      - gop 3+ dong trong lien tiep ve toi da mot dong trong,
      - strip dau/cuoi.
    Nho vay markdown (bang, danh sach, code fence) van xuong dong dung khi render.
    """
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return cleaned.strip()


def normalize_lookup(value: Any) -> str:
    return normalize_text(value).casefold()


def parse_bool_flag(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = normalize_lookup(value)
    if normalized in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    return default


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


def empty_chat_sessions() -> dict[str, Any]:
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
