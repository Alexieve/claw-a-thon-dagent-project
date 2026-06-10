import copy
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


DATA_DIR = Path(__file__).parent / "data"
RAW_EVENTS_PATH = DATA_DIR / "raw_events.jsonl"
CANDIDATES_PATH = DATA_DIR / "knowledge_candidates.json"
KNOWLEDGE_BASE_PATH = DATA_DIR / "knowledge_base.json"
DOCUMENT_CHUNKS_PATH = DATA_DIR / "document_chunks.jsonl"

ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
ALLOWED_KINDS = {"metric", "term", "dimension", "business_rule", "synonym"}
ALLOWED_CANDIDATE_STATUSES = {"pending_review", "approved", "rejected", "conflict"}


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


def empty_candidates() -> dict[str, Any]:
    return {"schema_version": 1, "candidates": {}}


def empty_knowledge_base() -> dict[str, Any]:
    return {"schema_version": 1, "knowledge": {}}


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


class KnowledgeStore:
    def __init__(
        self,
        *,
        raw_events_path: Path | str = RAW_EVENTS_PATH,
        candidates_path: Path | str = CANDIDATES_PATH,
        knowledge_base_path: Path | str = KNOWLEDGE_BASE_PATH,
        document_chunks_path: Path | str = DOCUMENT_CHUNKS_PATH,
        parser: KnowledgeParser | None = None,
    ) -> None:
        self.raw_events_path = Path(raw_events_path)
        self.candidates_path = Path(candidates_path)
        self.knowledge_base_path = Path(knowledge_base_path)
        self.document_chunks_path = Path(document_chunks_path)
        self.parser = parser or KnowledgeParser()

    def bootstrap(self) -> None:
        self.candidates_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.candidates_path.exists():
            self._save_json(self.candidates_path, empty_candidates())
        if not self.knowledge_base_path.exists():
            self._save_json(self.knowledge_base_path, empty_knowledge_base())
        if not self.raw_events_path.exists():
            self.raw_events_path.write_text("", encoding="utf-8")
        if not self.document_chunks_path.exists():
            self.document_chunks_path.write_text("", encoding="utf-8")

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
        self._append_jsonl(self.raw_events_path, event)
        return copy.deepcopy(event)

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
            return {"raw_event": event, "candidates": []}

        saved = [self.add_candidate(candidate) for candidate in candidates]
        return {"raw_event": event, "candidates": saved}

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
        all_candidates: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunk_text(cleaned)):
            chunk_record = {
                "id": new_id("chunk"),
                "document_id": document_id,
                "title": normalize_text(title),
                "chunk_index": index,
                "text": chunk,
                "created_at": now_iso(),
            }
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
            all_candidates.extend(taught["candidates"])

        return {"document_id": document_id, "chunks": chunks, "candidates": all_candidates}

    def add_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        data = self._load_candidates()
        normalized = self._normalize_candidate(candidate)
        existing = self._find_knowledge_by_name(normalized["name"])
        if existing and not self._definitions_compatible(existing.get("canonical_definition", ""), normalized["definition"]):
            normalized["status"] = "conflict"
            normalized["conflict_with"] = existing["id"]
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
        candidate["conflict_with"] = "" if knowledge else candidate.get("conflict_with", "")
        data["candidates"][candidate_id] = candidate
        self._save_json(self.candidates_path, data)
        return {"candidate": copy.deepcopy(candidate), "knowledge": copy.deepcopy(knowledge)}

    def search_knowledge(self, query: str = "") -> list[dict[str, Any]]:
        data = self._load_knowledge_base()
        normalized_query = normalize_lookup(query)
        records = []
        for record in data["knowledge"].values():
            if record.get("status") != "approved":
                continue
            haystack = " ".join(
                [
                    record.get("name", ""),
                    record.get("canonical_definition", ""),
                    record.get("domain", ""),
                    record.get("owner", ""),
                    " ".join(record.get("paraphrases", [])),
                    " ".join(record.get("conditions", [])),
                ]
            )
            if not normalized_query or normalized_query in normalize_lookup(haystack):
                records.append(copy.deepcopy(record))
        return sorted(records, key=lambda item: item.get("name", ""))

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
            elif candidate.get("status") == "pending_review":
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

    def _approve_candidate(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        existing = self._find_knowledge_by_name(candidate["name"])
        if existing and not self._definitions_compatible(
            existing.get("canonical_definition", ""), candidate.get("definition", "")
        ):
            candidate["status"] = "conflict"
            candidate["conflict_with"] = existing["id"]
            return None

        base = self._load_knowledge_base()
        if existing:
            record = base["knowledge"][existing["id"]]
            if candidate.get("definition") and not record.get("canonical_definition"):
                record["canonical_definition"] = candidate["definition"]
            record["paraphrases"] = unique_values(record.get("paraphrases", []) + candidate.get("paraphrases", []))
            record["conditions"] = unique_values(record.get("conditions", []) + candidate.get("conditions", []))
            if candidate.get("formula") and not record.get("formula"):
                record["formula"] = candidate["formula"]
            if candidate.get("domain") and not record.get("domain"):
                record["domain"] = candidate["domain"]
            if candidate.get("owner") and not record.get("owner"):
                record["owner"] = candidate["owner"]
            record["evidence_event_ids"] = unique_values(record.get("evidence_event_ids", []) + [candidate["source_event_id"]])
            record["candidate_ids"] = unique_values(record.get("candidate_ids", []) + [candidate["id"]])
            record["updated_at"] = now_iso()
        else:
            record = {
                "id": new_id("kn"),
                "kind": candidate.get("kind") if candidate.get("kind") != "synonym" else "term",
                "name": candidate["name"],
                "canonical_definition": candidate.get("definition", ""),
                "paraphrases": unique_values(candidate.get("paraphrases", [])),
                "formula": candidate.get("formula"),
                "conditions": unique_values(candidate.get("conditions", [])),
                "domain": candidate.get("domain", ""),
                "owner": candidate.get("owner", ""),
                "status": "approved",
                "evidence_event_ids": unique_values([candidate["source_event_id"]]),
                "candidate_ids": unique_values([candidate["id"]]),
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            base["knowledge"][record["id"]] = record

        self._save_json(self.knowledge_base_path, base)
        return record

    def _normalize_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "id": normalize_text(candidate.get("id")) or new_id("cand"),
            "source_event_id": normalize_text(candidate.get("source_event_id")),
            "kind": normalize_text(candidate.get("kind")) or "term",
            "name": normalize_text(candidate.get("name")),
            "definition": normalize_text(candidate.get("definition")),
            "paraphrases": unique_values(candidate.get("paraphrases", [])),
            "formula": normalize_text(candidate.get("formula")) or None,
            "conditions": unique_values(candidate.get("conditions", [])),
            "domain": normalize_text(candidate.get("domain")),
            "owner": normalize_text(candidate.get("owner")),
            "confidence": normalize_confidence(candidate.get("confidence"), default=0.0),
            "status": normalize_text(candidate.get("status")) or "pending_review",
            "conflict_with": normalize_text(candidate.get("conflict_with")),
            "created_at": normalize_text(candidate.get("created_at")) or now_iso(),
        }
        if normalized["kind"] not in ALLOWED_KINDS:
            normalized["kind"] = "term"
        if normalized["status"] not in ALLOWED_CANDIDATE_STATUSES:
            normalized["status"] = "pending_review"
        if not normalized["name"]:
            raise ValueError("Candidate thiếu name")
        return normalized

    def _editable_candidate_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"kind", "name", "definition", "paraphrases", "formula", "conditions", "domain", "owner", "confidence"}
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

    def _load_candidates(self) -> dict[str, Any]:
        return self._load_json(self.candidates_path, empty_candidates)

    def _load_knowledge_base(self) -> dict[str, Any]:
        return self._load_json(self.knowledge_base_path, empty_knowledge_base)

    def _load_json(self, path: Path, default_factory) -> dict[str, Any]:
        self.bootstrap_minimal(path, default_factory)
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data

    def _save_json(self, path: Path, data: dict[str, Any]) -> None:
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
