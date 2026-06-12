from __future__ import annotations

import json
import copy
import re
from pathlib import Path
from typing import Any

from .constants import RUNTIME_SKILLS_PATH
from .utils import normalize_lookup, normalize_text, unique_values


def parse_skill_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    raw = text[3:end].strip()
    body = text[end + 4 :].lstrip()
    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[normalize_text(key)] = normalize_text(value).strip("\"'")
    return metadata, body


def extract_markdown_sections(body: str, section_names: list[str], *, max_chars: int) -> list[str]:
    if not section_names:
        return [body[:max_chars].strip()] if body.strip() else []
    wanted = {normalize_lookup(name) for name in section_names}
    lines = body.splitlines()
    sections: list[str] = []
    current_title = ""
    current_lines: list[str] = []
    for line in lines:
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            if normalize_lookup(current_title) in wanted and current_lines:
                sections.append("\n".join(current_lines).strip())
            current_title = normalize_text(heading.group(1))
            current_lines = [line]
            continue
        if current_title:
            current_lines.append(line)
    if normalize_lookup(current_title) in wanted and current_lines:
        sections.append("\n".join(current_lines).strip())
    rendered = "\n\n".join(section for section in sections if section)
    if rendered:
        return [rendered[:max_chars].strip()]
    return [body[:max_chars].strip()] if body.strip() else []


class RuntimeSkillRegistry:
    def __init__(self, skills_path: Path = RUNTIME_SKILLS_PATH) -> None:
        self.skills_path = skills_path

    def enabled_skills(self) -> list[dict[str, Any]]:
        if not self.skills_path.exists():
            return []
        skills: list[dict[str, Any]] = []
        for skill_file in sorted(self.skills_path.glob("*/SKILL.md")):
            runtime_path = skill_file.parent / "runtime.json"
            if not runtime_path.exists():
                continue
            try:
                runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if runtime.get("enabled") is not True:
                continue
            try:
                raw_skill = skill_file.read_text(encoding="utf-8")
            except OSError:
                continue
            frontmatter, body = parse_skill_frontmatter(raw_skill)
            name = normalize_text(frontmatter.get("name")) or skill_file.parent.name
            skills.append(
                {
                    "name": name,
                    "description": normalize_text(frontmatter.get("description")),
                    "path": str(skill_file),
                    "runtime": runtime,
                    "body": body,
                }
            )
        return skills

    def query_candidates(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        cleaned_query = normalize_lookup(query)
        scored: list[tuple[int, dict[str, Any]]] = []
        for skill in self.enabled_skills():
            runtime = skill.get("runtime", {}) if isinstance(skill.get("runtime"), dict) else {}
            query_tokens = set(cleaned_query.split())
            haystack = normalize_lookup(
                " ".join(
                    [
                        skill.get("name", ""),
                        skill.get("description", ""),
                        " ".join(runtime.get("trigger_terms", []) if isinstance(runtime.get("trigger_terms"), list) else []),
                        " ".join(runtime.get("domains", []) if isinstance(runtime.get("domains"), list) else []),
                        " ".join(runtime.get("tables", []) if isinstance(runtime.get("tables"), list) else []),
                    ]
                )
            )
            haystack_tokens = set(haystack.split())
            fallback_words = [
                word
                for word in cleaned_query.split()
                if len(word) > 2
                and word
                not in {
                    "about",
                    "with",
                    "the",
                    "and",
                    "for",
                    "from",
                    "when",
                    "user",
                    "need",
                    "needs",
                    "want",
                    "wants",
                    "help",
                }
            ]
            score = 0
            for term in self._runtime_terms(runtime):
                normalized = normalize_lookup(term)
                if normalized and self._runtime_term_matches(normalized, cleaned_query, query_tokens):
                    score += 10
                elif normalized and normalized in haystack and self._runtime_term_matches(normalized, cleaned_query, query_tokens):
                    score += 4
            if not score and cleaned_query and any(word in haystack_tokens for word in fallback_words):
                score = 1
            if score > 0:
                card = {
                    "name": skill.get("name", ""),
                    "description": skill.get("description", ""),
                    "score": score,
                    "matched_by": "runtime_metadata",
                }
                scored.append((score, {**skill, "card": card}))
        return [item for _score, item in sorted(scored, key=lambda pair: (pair[0], pair[1].get("name", "")), reverse=True)[:limit]]

    def skill_card(self, skill: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(skill.get("card", {"name": skill.get("name", ""), "description": skill.get("description", ""), "score": 0}))

    def skill_payload(self, skill: dict[str, Any]) -> dict[str, Any]:
        runtime = skill.get("runtime", {}) if isinstance(skill.get("runtime"), dict) else {}
        section_names = runtime.get("instruction_sections") if isinstance(runtime.get("instruction_sections"), list) else []
        max_chars = int(runtime.get("max_instruction_chars") or 4000)
        return {
            "name": skill.get("name", ""),
            "description": skill.get("description", ""),
            "instructions": extract_markdown_sections(skill.get("body", ""), [str(item) for item in section_names], max_chars=max_chars),
        }

    def _runtime_terms(self, runtime: dict[str, Any]) -> list[str]:
        terms: list[str] = []
        for key in ["trigger_terms", "domains", "tables"]:
            values = runtime.get(key)
            if isinstance(values, list):
                terms.extend(str(item) for item in values)
        return unique_values(terms)

    def _runtime_term_matches(self, normalized_term: str, cleaned_query: str, query_tokens: set[str]) -> bool:
        if not normalized_term:
            return False
        if " " not in normalized_term and len(normalized_term) <= 3:
            return normalized_term in query_tokens
        return normalized_term in cleaned_query
