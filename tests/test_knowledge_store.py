import tempfile
import unittest
from pathlib import Path

from knowledge_store import KnowledgeParser, KnowledgeStore, extract_acronyms


class RankingParser(KnowledgeParser):
    def rank_knowledge(self, *, query, records):
        return [record["id"] for record in records if record["name"] == "ARPU"]


class BroadRankingParser(KnowledgeParser):
    def rank_knowledge(self, *, query, records):
        return [record["id"] for record in records]


class ParentheticalNameParser(KnowledgeParser):
    def parse(self, *, text, source_event_id, stakeholder="", team="", domain="", owner=""):
        return [
            {
                "id": "cand_test_parenthetical",
                "source_event_id": source_event_id,
                "kind": "metric",
                "name": "NPU (New Paying User)",
                "definition": "User phát sinh thanh toán lần đầu tiên trong kỳ báo cáo",
                "paraphrases": ["First payment user"],
                "formula": "COUNT(user_id) WHERE first_payment_date IN reporting_period",
                "conditions": [],
                "domain": domain or team,
                "owner": owner or stakeholder,
                "confidence": 0.95,
                "status": "pending_review",
                "conflict_with": "",
            }
        ]


class KnowledgeStoreTest(unittest.TestCase):
    def make_store(self, parser=None) -> KnowledgeStore:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        store = KnowledgeStore(
            raw_events_path=root / "raw_events.jsonl",
            candidates_path=root / "knowledge_candidates.json",
            knowledge_base_path=root / "knowledge_base.json",
            document_chunks_path=root / "document_chunks.jsonl",
            teaching_sessions_path=root / "teaching_sessions.json",
            parser=parser or KnowledgeParser(),
        )
        store.bootstrap()
        return store

    def test_extract_acronyms_keeps_order_and_uniqueness(self):
        self.assertEqual(extract_acronyms("FPU and NPU, then FPU again"), ["FPU", "NPU"])

    def test_default_storage_backend_is_json(self):
        store = self.make_store()

        self.assertEqual(store.storage_status(), {"backend": "json", "database_configured": False})

    def test_teach_text_confirmed_new_knowledge_goes_directly_to_kb(self):
        store = self.make_store()

        result = store.teach_text(
            text="FPU là user có first payment. Team Growth hay gọi là paid user đầu tiên.",
            stakeholder="Linh",
            team="Growth",
        )

        self.assertEqual(result["raw_event"]["source_type"], "manual_text")
        self.assertEqual(result["change_requests"], [])
        self.assertEqual(len(result["knowledge_created"]), 1)
        knowledge = result["knowledge_created"][0]
        self.assertEqual(knowledge["name"], "FPU")
        self.assertEqual(knowledge["status"], "approved")
        self.assertEqual(knowledge["owner"], "Linh")
        self.assertEqual(knowledge["version"], 1)
        self.assertIn("paid user đầu tiên", knowledge["paraphrases"])
        self.assertEqual(store.search_knowledge("FPU")[0]["name"], "FPU")

    def test_teaching_session_confirm_new_knowledge_commits_to_kb(self):
        store = self.make_store()
        started = store.start_teach_session(
            message="ARPU là doanh thu trung bình trên mỗi user trong kỳ.",
            stakeholder="Mai",
            team="Revenue",
        )

        self.assertEqual(started["status"], "awaiting_confirmation")
        confirmed = store.confirm_teach_session(session_id=started["session_id"], decision="confirm")

        self.assertEqual(confirmed["session"]["status"], "committed")
        self.assertEqual(len(confirmed["knowledge_created"]), 1)
        self.assertEqual(confirmed["knowledge_created"][0]["name"], "ARPU")
        self.assertEqual(store.search_knowledge("ARPU")[0]["owner"], "Mai")

    def test_existing_knowledge_creates_pending_change_without_updating_kb(self):
        store = self.make_store()
        created = store.teach_text(text="NPU là New Paying User.", stakeholder="Alice", team="Growth")
        knowledge = created["knowledge_created"][0]

        second = store.teach_text(text="NPU là Net Promoter User.", stakeholder="Bob", team="Growth")

        self.assertEqual(second["knowledge_created"], [])
        self.assertEqual(len(second["change_requests"]), 1)
        change = second["change_requests"][0]
        self.assertEqual(change["status"], "pending_change")
        self.assertEqual(change["target_knowledge_id"], knowledge["id"])
        self.assertEqual(change["proposed_by"], "Bob")
        self.assertEqual(change["original_owner"], "Alice")
        self.assertEqual(store.search_knowledge("NPU")[0]["canonical_definition"], "New Paying User")

    def test_approve_pending_change_updates_kb_version_and_keeps_original_owner(self):
        store = self.make_store()
        store.teach_text(text="NPU là New Paying User.", stakeholder="Alice", team="Growth")
        second = store.teach_text(text="NPU là Net Promoter User.", stakeholder="Bob", team="Growth")
        candidate_id = second["change_requests"][0]["id"]

        reviewed = store.review_candidate(candidate_id=candidate_id, decision="approve")

        knowledge = reviewed["knowledge"]
        self.assertEqual(reviewed["candidate"]["status"], "approved")
        self.assertEqual(knowledge["canonical_definition"], "Net Promoter User")
        self.assertEqual(knowledge["owner"], "Alice")
        self.assertEqual(knowledge["version"], 2)
        self.assertEqual(len(knowledge["change_history"]), 1)
        self.assertEqual(knowledge["change_history"][0]["changed_by"], "Bob")

    def test_reject_pending_change_keeps_existing_kb(self):
        store = self.make_store()
        store.teach_text(text="NPU là New Paying User.", stakeholder="Alice", team="Growth")
        second = store.teach_text(text="NPU là Net Promoter User.", stakeholder="Bob", team="Growth")
        candidate_id = second["change_requests"][0]["id"]

        reviewed = store.review_candidate(candidate_id=candidate_id, decision="reject")

        self.assertEqual(reviewed["candidate"]["status"], "rejected")
        self.assertEqual(store.search_knowledge("NPU")[0]["canonical_definition"], "New Paying User")

    def test_small_existing_change_still_requires_approval(self):
        store = self.make_store()
        store.teach_text(text="FPU là user có first payment.", stakeholder="Alice", team="Growth")
        second = store.teach_text(
            text="FPU là user có first payment. Còn gọi là paid user đầu tiên.",
            stakeholder="Bob",
            team="Growth",
        )

        self.assertEqual(len(second["change_requests"]), 1)
        self.assertEqual(store.search_knowledge("paid user đầu tiên"), [])

        store.review_candidate(candidate_id=second["change_requests"][0]["id"], decision="approve")
        record = store.search_knowledge("paid user đầu tiên")[0]
        self.assertIn("paid user đầu tiên", record["paraphrases"])
        self.assertEqual(record["owner"], "Alice")

    def test_analyze_text_separates_known_pending_and_unknown(self):
        store = self.make_store()
        store.teach_text(text="FPU là user có first payment.", stakeholder="Alice")
        store.teach_text(text="NAU là New Active User.", stakeholder="Alice")
        store.teach_text(text="NAU là Net Active User.", stakeholder="Bob")

        analysis = store.analyze_text("So sánh FPU, NAU và NPR")

        self.assertEqual([item["name"] for item in analysis["known"]], ["FPU", "NAU"])
        self.assertEqual([item["name"] for item in analysis["pending"]], ["NAU"])
        self.assertIn("NPR", analysis["unknown"])

    def test_ingest_document_uses_confirmed_teach_policy(self):
        store = self.make_store()

        result = store.ingest_document(text="FPU là user có first payment.", title="Metric handbook")

        self.assertEqual(len(result["chunks"]), 1)
        self.assertEqual(len(result["knowledge_created"]), 1)
        self.assertEqual(result["knowledge_created"][0]["name"], "FPU")

    def test_fallback_parser_creates_low_confidence_knowledge_for_unknown_acronym(self):
        store = self.make_store()

        result = store.teach_text(text="Team đang bàn về NPR nhưng chưa thống nhất.")

        self.assertEqual(result["knowledge_created"][0]["name"], "NPR")
        self.assertLess(result["knowledge_created"][0]["confidence"] if "confidence" in result["knowledge_created"][0] else 0.3, 0.5)

    def test_search_knowledge_uses_llm_ranker_when_available(self):
        store = self.make_store(parser=RankingParser())
        store.teach_text(text="FPU là user có first payment.")
        store.teach_text(text="ARPU là doanh thu trung bình trên mỗi user.")

        result = store.search_knowledge("doanh thu theo user")

        self.assertEqual([item["name"] for item in result], ["ARPU"])

    def test_parenthetical_acronym_name_is_canonicalized(self):
        store = self.make_store(parser=ParentheticalNameParser())

        result = store.teach_text(text="NPU là New Paying User.", stakeholder="Alice", team="Growth")

        knowledge = result["knowledge_created"][0]
        self.assertEqual(knowledge["name"], "NPU")
        self.assertIn("NPU (New Paying User)", knowledge["paraphrases"])
        self.assertIn("New Paying User", knowledge["paraphrases"])

    def test_acronym_search_does_not_allow_broad_llm_results(self):
        store = self.make_store(parser=BroadRankingParser())
        store.teach_text(text="FPU là user có first payment.")
        store.teach_text(text="ARPU là doanh thu trung bình trên mỗi user.")
        store.teach_text(text="NPU là New Paying User.")

        result = store.search_knowledge("NPU")

        self.assertEqual([item["name"] for item in result], ["NPU"])


if __name__ == "__main__":
    unittest.main()
