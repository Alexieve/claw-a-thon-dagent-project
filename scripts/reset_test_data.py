#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional outside the app venv
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ZALOPAY_OWNER = "Zalopay OTA"
ZALOPAY_DOMAIN = "Zalopay AIR/OTA"
TEST_MARKERS = {"seed", "codex", "test", "demo", "local", "bootstrap"}


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def has_test_marker(value: Any) -> bool:
    normalized = normalize(value)
    return bool(normalized and any(marker in normalized for marker in TEST_MARKERS))


def is_zalopay_record(record: dict[str, Any], prefixes: tuple[str, ...]) -> bool:
    record_id = str(record.get("id") or "")
    return (
        record.get("owner") == ZALOPAY_OWNER
        or record.get("domain") == ZALOPAY_DOMAIN
        or record_id.startswith(prefixes)
    )


def should_delete_record(record: dict[str, Any], prefixes: tuple[str, ...]) -> bool:
    if is_zalopay_record(record, prefixes):
        return False
    record_id = str(record.get("id") or "")
    if record_id.startswith(("kn_seed_", "dict_seed_", "qex_seed_", "cand_seed_")):
        return True
    return has_test_marker(record.get("owner")) or has_test_marker(record.get("created_by"))


def filter_bucket(
    *,
    label: str,
    data: dict[str, Any],
    bucket_key: str,
    prefixes: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    original = data.get(bucket_key, {})
    kept: dict[str, Any] = {}
    deleted: dict[str, Any] = {}
    for record_id, record in original.items():
        if should_delete_record(record, prefixes):
            deleted[record_id] = record
        else:
            kept[record_id] = record
    return {**data, bucket_key: kept}, {"label": label, "kept": kept, "deleted": deleted}


def compact(record: dict[str, Any]) -> str:
    title = record.get("name") or record.get("table") or record.get("question") or record.get("target_knowledge_id") or ""
    return f"{record.get('id', '')} ({title})"


def print_report(reports: list[dict[str, Any]]) -> None:
    print("Selective reset preview")
    for report in reports:
        deleted = report["deleted"]
        kept = report["kept"]
        print(f"- {report['label']}: keep={len(kept)} delete={len(deleted)}")
        for record in list(deleted.values())[:10]:
            print(f"  delete: {compact(record)}")
        if len(deleted) > 10:
            print(f"  ... {len(deleted) - 10} more")


def build_cleaned_payloads(include_candidates: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    knowledge = load_json(DATA_DIR / "knowledge_base.json", {"schema_version": 1, "knowledge": {}})
    dictionary = load_json(DATA_DIR / "data_dictionary.json", {"schema_version": 1, "records": {}})
    examples = load_json(DATA_DIR / "question_examples.json", {"schema_version": 1, "examples": {}})
    candidates = load_json(DATA_DIR / "knowledge_candidates.json", {"schema_version": 1, "candidates": {}})

    cleaned_knowledge, knowledge_report = filter_bucket(
        label="knowledge_base",
        data=knowledge,
        bucket_key="knowledge",
        prefixes=("kn_zlp_air_",),
    )
    cleaned_dictionary, dictionary_report = filter_bucket(
        label="data_dictionary",
        data=dictionary,
        bucket_key="records",
        prefixes=("dict_zlp_air_",),
    )
    cleaned_examples, examples_report = filter_bucket(
        label="question_examples",
        data=examples,
        bucket_key="examples",
        prefixes=("qex_zlp_air_",),
    )
    cleaned_candidates, candidates_report = filter_bucket(
        label="knowledge_candidates",
        data=candidates,
        bucket_key="candidates",
        prefixes=("cand_zlp_air_",),
    )
    reports = [knowledge_report, dictionary_report, examples_report]
    if include_candidates:
        reports.append(candidates_report)
    else:
        candidates_report["label"] = "knowledge_candidates (dry-run only; pass --include-candidates to write)"
        reports.append(candidates_report)
        cleaned_candidates = None
    return cleaned_knowledge, cleaned_dictionary, cleaned_examples, cleaned_candidates, reports


def push_sql(knowledge: dict[str, Any], dictionary: dict[str, Any], examples: dict[str, Any]) -> None:
    if load_dotenv:
        load_dotenv(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for --push-sql")
    sys.path.insert(0, str(ROOT))
    from knowledge_store import PostgresStorage

    storage = PostgresStorage(database_url)
    storage.bootstrap()
    storage.save_knowledge_base(knowledge)
    storage.save_data_dictionary(dictionary)
    storage.save_question_examples(examples)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset seed/test data while keeping Zalopay AIR/OTA records.")
    parser.add_argument("--dry-run", action="store_true", help="Preview reset without writing. Default when no write flag is set.")
    parser.add_argument("--write-json", action="store_true", help="Write cleaned local JSON files.")
    parser.add_argument("--push-sql", action="store_true", help="Push cleaned KB/dictionary/examples to Postgres using DATABASE_URL.")
    parser.add_argument("--include-candidates", action="store_true", help="Also write cleaned knowledge_candidates.json.")
    args = parser.parse_args()

    if not (args.dry_run or args.write_json or args.push_sql):
        args.dry_run = True

    knowledge, dictionary, examples, candidates, reports = build_cleaned_payloads(args.include_candidates)
    print_report(reports)

    if args.write_json:
        save_json(DATA_DIR / "knowledge_base.json", knowledge)
        save_json(DATA_DIR / "data_dictionary.json", dictionary)
        save_json(DATA_DIR / "question_examples.json", examples)
        if candidates is not None:
            save_json(DATA_DIR / "knowledge_candidates.json", candidates)
        print("- wrote cleaned JSON")
    if args.push_sql:
        push_sql(knowledge, dictionary, examples)
        print("- pushed cleaned KB/dictionary/examples to Postgres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
