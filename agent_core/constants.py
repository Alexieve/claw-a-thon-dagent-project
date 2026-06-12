import re
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_EVENTS_PATH = DATA_DIR / "raw_events.jsonl"
CANDIDATES_PATH = DATA_DIR / "knowledge_candidates.json"
KNOWLEDGE_BASE_PATH = DATA_DIR / "knowledge_base.json"
DOCUMENT_CHUNKS_PATH = DATA_DIR / "document_chunks.jsonl"
TEACHING_SESSIONS_PATH = DATA_DIR / "teaching_sessions.json"
CHAT_SESSIONS_PATH = DATA_DIR / "chat_sessions.json"
DATA_DICTIONARY_PATH = DATA_DIR / "data_dictionary.json"
QUESTION_EXAMPLES_PATH = DATA_DIR / "question_examples.json"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
RUNTIME_SKILLS_PATH = Path(__file__).resolve().parent.parent / ".codex" / "skills"

ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
ALLOWED_KINDS = {"metric", "term", "dimension", "business_rule", "synonym"}
ALLOWED_CANDIDATE_STATUSES = {"pending_review", "pending_change", "approved", "rejected", "conflict"}
ALLOWED_TEACHING_SESSION_STATUSES = {
    "awaiting_teach_confirmation",
    "clarifying",
    "awaiting_confirmation",
    "committed",
    "pending_approval",
    "cancelled",
}
