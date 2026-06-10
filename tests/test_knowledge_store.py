import tempfile
import unittest
from pathlib import Path

from knowledge_store import KnowledgeParser, KnowledgeStore, extract_acronyms


class KnowledgeStoreTest(unittest.TestCase):
    def make_store(self) -> KnowledgeStore:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        store = KnowledgeStore(
            raw_events_path=root / "raw_events.jsonl",
            candidates_path=root / "knowledge_candidates.json",
            knowledge_base_path=root / "knowledge_base.json",
            document_chunks_path=root / "document_chunks.jsonl",
            parser=KnowledgeParser(),
        )
        store.bootstrap()
        return store

    def test_extract_acronyms_keeps_order_and_uniqueness(self):
        self.assertEqual(extract_acronyms("FPU and NPU, then FPU again"), ["FPU", "NPU"])

    def test_teach_text_appends_raw_event_and_creates_candidate(self):
        store = self.make_store()
        result = store.teach_text(
            text="FPU là user có first payment. Team Growth hay gọi là paid user đầu tiên.",
            stakeholder="Linh",
            team="Growth",
        )

        self.assertEqual(result["raw_event"]["source_type"], "manual_text")
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["name"], "FPU")
        self.assertEqual(candidate["status"], "pending_review")
        self.assertIn("paid user đầu tiên", candidate["paraphrases"])

    def test_approve_candidate_creates_knowledge(self):
        store = self.make_store()
        taught = store.teach_text(text="FPU là user có first payment.", team="Growth")
        candidate_id = taught["candidates"][0]["id"]

        reviewed = store.review_candidate(candidate_id=candidate_id, decision="approve")

        self.assertEqual(reviewed["candidate"]["status"], "approved")
        self.assertEqual(reviewed["knowledge"]["name"], "FPU")
        self.assertEqual(reviewed["knowledge"]["canonical_definition"], "user có first payment")
        self.assertEqual(store.search_knowledge("FPU")[0]["name"], "FPU")

    def test_reject_candidate_does_not_create_knowledge(self):
        store = self.make_store()
        taught = store.teach_text(text="NPU là new paying user.")
        candidate_id = taught["candidates"][0]["id"]

        reviewed = store.review_candidate(candidate_id=candidate_id, decision="reject")

        self.assertEqual(reviewed["candidate"]["status"], "rejected")
        self.assertEqual(store.search_knowledge("NPU"), [])

    def test_conflict_does_not_overwrite_canonical_knowledge(self):
        store = self.make_store()
        first = store.teach_text(text="NPU là New Paying User.")
        store.review_candidate(candidate_id=first["candidates"][0]["id"], decision="approve")

        second = store.teach_text(text="NPU là Net Promoter User.")

        candidate = second["candidates"][0]
        self.assertEqual(candidate["status"], "conflict")
        reviewed = store.review_candidate(candidate_id=candidate["id"], decision="approve")
        self.assertEqual(reviewed["candidate"]["status"], "conflict")
        self.assertIsNone(reviewed["knowledge"])
        self.assertEqual(store.search_knowledge("NPU")[0]["canonical_definition"], "New Paying User")

    def test_approve_synonym_merges_paraphrase(self):
        store = self.make_store()
        first = store.teach_text(text="FPU là user có first payment.")
        store.review_candidate(candidate_id=first["candidates"][0]["id"], decision="approve")
        second = store.teach_text(text="FPU là user có first payment. Còn gọi là paid user đầu tiên.")

        store.review_candidate(candidate_id=second["candidates"][0]["id"], decision="approve")

        record = store.search_knowledge("FPU")[0]
        self.assertIn("paid user đầu tiên", record["paraphrases"])

    def test_analyze_text_separates_known_pending_conflict_and_unknown(self):
        store = self.make_store()
        approved = store.teach_text(text="FPU là user có first payment.")
        store.review_candidate(candidate_id=approved["candidates"][0]["id"], decision="approve")
        store.teach_text(text="NPU là new paying user.")
        conflict_seed = store.teach_text(text="NAU là New Active User.")
        store.review_candidate(candidate_id=conflict_seed["candidates"][0]["id"], decision="approve")
        store.teach_text(text="NAU là Net Active User.")

        analysis = store.analyze_text("So sánh FPU, NPU, NAU và NPR")

        self.assertEqual([item["name"] for item in analysis["known"]], ["FPU", "NAU"])
        self.assertEqual([item["name"] for item in analysis["pending"]], ["NPU"])
        self.assertEqual([item["name"] for item in analysis["conflicts"]], ["NAU"])
        self.assertIn("NPR", analysis["unknown"])

    def test_ingest_document_creates_chunks_and_candidates(self):
        store = self.make_store()

        result = store.ingest_document(text="FPU là user có first payment.", title="Metric handbook")

        self.assertEqual(len(result["chunks"]), 1)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["name"], "FPU")

    def test_fallback_parser_creates_low_confidence_candidate_for_unknown_acronym(self):
        store = self.make_store()

        result = store.teach_text(text="Team đang bàn về NPR nhưng chưa thống nhất.")

        self.assertEqual(result["candidates"][0]["name"], "NPR")
        self.assertLess(result["candidates"][0]["confidence"], 0.5)


if __name__ == "__main__":
    unittest.main()
