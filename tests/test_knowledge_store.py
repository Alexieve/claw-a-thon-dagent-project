import tempfile
import time
import unittest
from pathlib import Path

from knowledge_store import KnowledgeParser, KnowledgeStore, RuntimeSkillRegistry, extract_acronyms


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


class FakeChatLLM:
    def __init__(self, *, plans=None, text="LLM trả lời tự nhiên từ context.") -> None:
        self.plans = list(plans or [{"action": "answer_direct", "answer": text, "confidence": 0.9}])
        self.text = text
        self.text_inputs = []

    def configured(self):
        return True

    def complete_json(self, *, system, user, temperature=0, model=None):
        if "draft SQL" in system or "draft SQL" in system.lower():
            return {}
        if "select runtime skills" in system:
            import json

            data = json.loads(user)
            names = [item.get("name") for item in data.get("candidates", [])]
            selected = ["air-sql-analyst"] if "air-sql-analyst" in names else []
            return {"selected_skills": selected, "reason": "selected by fake runtime skill selector" if selected else ""}
        if "action planner" in system:
            if len(self.plans) > 1:
                return self.plans.pop(0)
            return self.plans[0]
        return {}

    def complete_text(self, *, system, user, temperature=0.2, model=None):
        if "final user-facing answer" in system:
            import json

            payload = json.loads(user)
            self.text_inputs.append({"system": system, "user": user, "temperature": temperature})
            return payload.get("draft_answer") or self.text
        self.text_inputs.append({"system": system, "user": user, "temperature": temperature})
        return self.text


class FailingTextLLM(FakeChatLLM):
    def complete_text(self, *, system, user, temperature=0.2, model=None):
        self.text_inputs.append({"system": system, "user": user, "temperature": temperature})
        raise ValueError("text synthesis failed")


class ViolatingSynthesisLLM(FakeChatLLM):
    def complete_text(self, *, system, user, temperature=0.2, model=None):
        self.text_inputs.append({"system": system, "user": user, "temperature": temperature})
        if "final user-facing answer" in system:
            return "```sql\nSELECT COUNT(*) FROM payment_air\n```"
        return self.text


class CapturingPlannerLLM(FakeChatLLM):
    def __init__(self, *, plan=None) -> None:
        super().__init__(plans=[plan or {"action": "answer_direct", "answer": "ok", "confidence": 0.9}])
        self.planner_inputs = []
        self.skill_selector_inputs = []

    def complete_json(self, *, system, user, temperature=0, model=None):
        if "select runtime skills" in system:
            import json

            self.skill_selector_inputs.append(json.loads(user))
        if "action planner" in system:
            import json

            self.planner_inputs.append(json.loads(user))
        return super().complete_json(system=system, user=user, temperature=temperature)


class ThinkWithMeLLM(CapturingPlannerLLM):
    def complete_json(self, *, system, user, temperature=0, model=None):
        if "select runtime skills" in system:
            import json

            data = json.loads(user)
            self.skill_selector_inputs.append(data)
            names = [item.get("name") for item in data.get("candidates", [])]
            selected = ["think-with-me"] if "think-with-me" in names else []
            return {"selected_skills": selected, "reason": "selected think-with-me for test" if selected else ""}
        return super().complete_json(system=system, user=user, temperature=temperature)


class FakeMemoryEventStore:
    def __init__(self, *, events=None, delay=0) -> None:
        self.events = list(events or [])
        self.delay = delay
        self.appended = []

    def append_event(self, *, chat_session, user_id, session_id, role, content):
        if self.delay:
            time.sleep(self.delay)
        self.appended.append({"role": role, "content": content, "created_at": "2026-06-12T00:00:00+00:00"})

    def list_recent_events(self, *, chat_session, user_id, session_id, limit):
        if self.delay:
            time.sleep(self.delay)
        return self.events[-limit:]


class KnowledgeStoreTest(unittest.TestCase):
    def make_store(self, parser=None, llm_client=None, **kwargs) -> KnowledgeStore:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        store = KnowledgeStore(
            raw_events_path=root / "raw_events.jsonl",
            candidates_path=root / "knowledge_candidates.json",
            knowledge_base_path=root / "knowledge_base.json",
            document_chunks_path=root / "document_chunks.jsonl",
            teaching_sessions_path=root / "teaching_sessions.json",
            chat_sessions_path=root / "chat_sessions.json",
            data_dictionary_path=root / "data_dictionary.json",
            question_examples_path=root / "question_examples.json",
            parser=parser or KnowledgeParser(),
            llm_client=llm_client,
            **kwargs,
        )
        store.bootstrap()
        return store

    def teach_rpu(self, store: KnowledgeStore):
        return store.teach_text(
            text="RPU là Revenue Per User, doanh thu trung bình trên mỗi active user. Công thức total revenue / active users.",
            stakeholder="Finance",
            team="Revenue",
        )["knowledge_created"][0]

    def add_rpu_dictionary(self, store: KnowledgeStore) -> None:
        store.add_data_dictionary(
            table="payments",
            description="Bảng giao dịch thanh toán",
            columns=[
                {
                    "name": "amount",
                    "business_meaning": "Doanh thu thanh toán",
                    "data_type": "numeric",
                    "aliases": ["revenue", "gmv", "payment amount"],
                },
                {
                    "name": "user_id",
                    "business_meaning": "User phát sinh giao dịch",
                    "data_type": "text",
                    "aliases": ["user", "active user"],
                },
                {
                    "name": "campaign_id",
                    "business_meaning": "Campaign của giao dịch",
                    "data_type": "text",
                    "aliases": ["campaign"],
                },
            ],
            relationships=[
                {"from": "payments.campaign_id", "to": "campaigns.id", "type": "many_to_one"},
            ],
            owner="data-team",
        )
        store.add_data_dictionary(
            table="campaigns",
            description="Bảng campaign marketing",
            columns=[
                {
                    "name": "id",
                    "business_meaning": "Khóa campaign",
                    "data_type": "text",
                    "aliases": ["campaign id"],
                },
                {
                    "name": "campaign_name",
                    "business_meaning": "Tên campaign",
                    "data_type": "text",
                    "aliases": ["campaign"],
                },
            ],
            owner="data-team",
        )

    def teach_arppu(self, store: KnowledgeStore):
        return store.teach_text(
            text="ARPPU là Average Revenue Per Paying User, doanh thu trung bình trên mỗi paying user. Công thức total revenue / paying users.",
            stakeholder="Finance",
            team="Revenue",
        )["knowledge_created"][0]

    def test_extract_acronyms_keeps_order_and_uniqueness(self):
        self.assertEqual(extract_acronyms("FPU and NPU, then FPU again"), ["FPU", "NPU"])

    def test_default_storage_backend_is_json(self):
        store = self.make_store()

        status = store.storage_status()

        self.assertEqual(status["backend"], "json")
        self.assertFalse(status["database_configured"])
        self.assertEqual(status["chat_context_backend"], "auto")
        self.assertFalse(status["chat_context_memory_configured"])

    def test_chat_agentbase_context_strict_requires_memory_config(self):
        store = self.make_store(
            chat_context_backend="agentbase",
            chat_context_memory_id="",
            chat_context_fallback_on_error=False,
        )

        with self.assertRaises(ValueError):
            store.chat(message="RPU là gì?", user_id="quynh", session_id="strict-memory")

    def test_auto_context_store_resolves_without_memory_name_error(self):
        store = self.make_store(chat_context_backend="auto", chat_context_memory_id="mem_test")

        backend, _event_store, _reason = store._resolve_context_store(user_id="quynh", session_id="auto-memory")

        self.assertIn(backend, {"agentbase", "local"})

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

    def test_search_data_dictionary_matches_column_alias(self):
        store = self.make_store()
        store.add_data_dictionary(
            table="payments",
            columns=[
                {
                    "name": "amount",
                    "business_meaning": "Doanh thu thanh toán",
                    "data_type": "numeric",
                    "aliases": ["revenue", "gmv"],
                }
            ],
        )

        result = store.search_data_dictionary("gmv")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["table"], "payments")

    def test_ask_data_question_without_dictionary_returns_missing_context(self):
        store = self.make_store()
        self.teach_rpu(store)

        result = store.ask_data_question("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "needs_dictionary")
        self.assertIn("RPU", [item["concept"] for item in result["missing"]])
        self.assertIn("campaign", [item["concept"] for item in result["missing"]])

    def test_ask_data_question_with_partial_dictionary_still_needs_dictionary(self):
        store = self.make_store()
        self.teach_rpu(store)
        store.add_data_dictionary(
            table="campaigns",
            columns=[
                {
                    "name": "campaign_name",
                    "business_meaning": "Tên campaign",
                    "data_type": "text",
                    "aliases": ["campaign"],
                }
            ],
        )

        result = store.ask_data_question("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "needs_dictionary")
        self.assertIn("RPU", [item["concept"] for item in result["missing"]])
        self.assertNotIn("campaign", [item["concept"] for item in result["missing"]])

    def test_missing_dictionary_data_answer_does_not_use_llm_sql(self):
        store = self.make_store(llm_client=FakeChatLLM(text="```sql\nSELECT 1\n```"))

        answer = store._synthesize_data_answer(
            "PU tháng trước",
            {
                "status": "needs_dictionary",
                "missing": [{"question": "PU lấy từ bảng/cột nào?"}],
            },
        )

        self.assertIn("chưa đủ mapping", answer)
        self.assertNotIn("SELECT 1", answer)

    def test_ask_data_question_with_enough_dictionary_returns_sql_draft(self):
        store = self.make_store()
        self.teach_rpu(store)
        self.add_rpu_dictionary(store)

        result = store.ask_data_question("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "sql_draft")
        self.assertEqual(result["used_example_ids"], [])
        self.assertIn("SUM(payments.amount)", result["sql"])
        self.assertIn("campaign_name", result["sql"])
        self.assertIn("GROUP BY", result["sql"])

    def test_ask_data_question_uses_nearby_question_example_when_available(self):
        store = self.make_store()
        self.teach_rpu(store)
        self.add_rpu_dictionary(store)
        example = store.add_question_example(
            question="RPU theo campaign",
            sql="SELECT campaign_name, SUM(amount) / COUNT(DISTINCT user_id) AS rpu FROM mart_rpu GROUP BY campaign_name;",
            explanation="Mẫu approved cho RPU theo campaign",
            concepts=["RPU", "campaign"],
            used_tables=["mart_rpu"],
        )

        result = store.ask_data_question("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "sql_draft")
        self.assertEqual(result["sql"], example["sql"])
        self.assertEqual(result["used_example_ids"], [example["id"]])

    def test_chat_freeform_metric_name_question_answers_naturally_with_planner(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "answer_direct",
                        "answer": "RPU dùng active user, còn ARPPU dùng paying user.",
                        "confidence": 0.9,
                    }
                ]
            )
        )
        self.teach_rpu(store)
        self.teach_arppu(store)

        result = store.chat(message="Tôi muốn biết doanh thu trung bình được gọi là gì?", user_id="quynh")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["intent"], "planner_answer")
        self.assertIn("RPU", result["answer"])
        self.assertIn("ARPPU", result["answer"])
        self.assertIn("active user", result["answer"])
        self.assertIn("paying user", result["answer"])
        self.assertTrue(result["debug"]["llm_used"])

    def test_chat_freeform_definition_question_uses_retrieved_knowledge(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[{"action": "answer_direct", "answer": "RPU là Revenue Per User.", "confidence": 0.9}]
            )
        )
        self.teach_rpu(store)

        result = store.chat(message="RPU là gì?")

        self.assertEqual(result["status"], "answered")
        self.assertIn("Revenue Per User", result["answer"])
        self.assertEqual(result["used_knowledge_ids"], [store.search_knowledge("RPU")[0]["id"]])

    def test_chat_without_llm_returns_llm_required(self):
        store = self.make_store()
        self.teach_rpu(store)

        result = store.chat(message="RPU là gì?")

        self.assertEqual(result["status"], "llm_required")
        self.assertEqual(result["intent"], "llm_required")
        self.assertFalse(result["debug"]["planner_used"])

    def test_chat_planner_receives_air_sql_runtime_skill_for_air_question(self):
        llm = CapturingPlannerLLM()
        store = self.make_store(llm_client=llm)
        store.teach_text(
            text="AOV là Average Order Value, giá trị đơn hàng trung bình.",
            stakeholder="Trang",
            team="Zalopay AIR/OTA",
            domain="Zalopay AIR/OTA",
            owner="Zalopay OTA",
        )

        result = store.chat(message="AOV Air là gì?", user_id="quynh", session_id="air-skill")

        skills = llm.planner_inputs[-1]["runtime_skills"]
        self.assertEqual(skills[0]["name"], "air-sql-analyst")
        self.assertTrue(any("Presto/Trino" in item for item in skills[0]["instructions"]))
        self.assertEqual(result["debug"]["runtime_skills_used"], ["air-sql-analyst"])
        candidate_names = [item["name"] for item in result["debug"]["runtime_skill_candidates"]]
        self.assertEqual(candidate_names, ["air-sql-analyst"])
        self.assertNotIn("agentbase", " ".join(candidate_names))
        self.assertEqual(llm.skill_selector_inputs, [])
        self.assertIn("auto-selected", result["debug"]["runtime_skill_selection_reason"])

    def test_chat_planner_skips_air_sql_runtime_skill_for_non_air_question(self):
        llm = CapturingPlannerLLM()
        store = self.make_store(llm_client=llm)

        store.chat(message="Bạn là ai?", user_id="quynh", session_id="general-skill")

        self.assertEqual(llm.planner_inputs[-1]["runtime_skills"], [])
        self.assertEqual(llm.skill_selector_inputs, [])

    def test_chat_can_disable_runtime_skill_per_request(self):
        llm = CapturingPlannerLLM()
        store = self.make_store(llm_client=llm)
        store.teach_text(
            text="AOV là Average Order Value, giá trị đơn hàng trung bình.",
            stakeholder="Trang",
            team="Zalopay AIR/OTA",
            domain="Zalopay AIR/OTA",
            owner="Zalopay OTA",
        )

        result = store.chat(
            message="AOV Air là gì?",
            user_id="quynh",
            session_id="air-skill-disabled",
            use_runtime_skills=False,
        )

        self.assertEqual(llm.planner_inputs[-1]["runtime_skills"], [])
        self.assertEqual(result["debug"]["runtime_skills_used"], [])
        self.assertFalse(result["debug"]["runtime_skills_enabled"])
        self.assertEqual(result["debug"]["runtime_skill_selection_reason"], "runtime skills disabled by request/config")
        self.assertEqual(llm.skill_selector_inputs, [])

    def test_chat_runtime_skill_config_default_can_be_disabled(self):
        llm = CapturingPlannerLLM()
        store = self.make_store(llm_client=llm, runtime_skills_enabled=False)
        store.teach_text(
            text="AOV là Average Order Value, giá trị đơn hàng trung bình.",
            stakeholder="Trang",
            team="Zalopay AIR/OTA",
            domain="Zalopay AIR/OTA",
            owner="Zalopay OTA",
        )

        result = store.chat(message="AOV Air là gì?", user_id="quynh", session_id="air-skill-config-disabled")

        self.assertEqual(llm.planner_inputs[-1]["runtime_skills"], [])
        self.assertFalse(result["debug"]["runtime_skills_enabled"])

    def test_chat_response_excludes_full_context_by_default(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[{"action": "answer_direct", "answer": "RPU là Revenue Per User.", "confidence": 0.9}]
            )
        )
        self.teach_rpu(store)

        result = store.chat(message="RPU là gì?", user_id="quynh", session_id="light-response")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["used_knowledge_ids"], [store.search_knowledge("RPU")[0]["id"]])
        self.assertNotIn("knowledge", result)
        self.assertNotIn("dictionary", result)
        self.assertNotIn("examples", result)
        self.assertIn("latency_ms", result["debug"])
        self.assertIn("total", result["debug"]["latency_ms"])
        self.assertIn("answer_synthesis", result["debug"]["latency_ms"])
        self.assertIn("save", result["debug"]["latency_ms"])
        self.assertIn("total_with_save", result["debug"]["latency_ms"])

    def test_chat_response_includes_full_context_when_debug_context_enabled(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[{"action": "answer_direct", "answer": "RPU là Revenue Per User.", "confidence": 0.9}]
            )
        )
        self.teach_rpu(store)

        result = store.chat(message="RPU là gì?", user_id="quynh", session_id="debug-response", debug_context=True)

        self.assertEqual(result["status"], "answered")
        self.assertIn("knowledge", result)
        self.assertEqual(result["knowledge"][0]["name"], "RPU")

    def test_runtime_skill_registry_requires_enabled_runtime_json(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        enabled = root / "enabled-skill"
        disabled = root / "disabled-skill"
        no_runtime = root / "no-runtime-skill"
        enabled.mkdir()
        disabled.mkdir()
        no_runtime.mkdir()
        enabled.joinpath("SKILL.md").write_text("---\nname: enabled-skill\ndescription: Enabled runtime skill.\n---\n\n## Core Workflow\nUse me.", encoding="utf-8")
        enabled.joinpath("runtime.json").write_text('{"enabled": true, "trigger_terms": ["alpha"], "instruction_sections": ["Core Workflow"]}', encoding="utf-8")
        disabled.joinpath("SKILL.md").write_text("---\nname: disabled-skill\ndescription: Disabled runtime skill.\n---\n\n## Core Workflow\nDo not use me.", encoding="utf-8")
        disabled.joinpath("runtime.json").write_text('{"enabled": false, "trigger_terms": ["alpha"]}', encoding="utf-8")
        no_runtime.joinpath("SKILL.md").write_text("---\nname: no-runtime-skill\ndescription: No runtime metadata.\n---\n\n## Core Workflow\nDo not use me.", encoding="utf-8")

        registry = RuntimeSkillRegistry(skills_path=root)
        candidates = registry.query_candidates("alpha")

        self.assertEqual([item["name"] for item in candidates], ["enabled-skill"])
        payload = registry.skill_payload(candidates[0])
        self.assertEqual(payload["name"], "enabled-skill")
        self.assertIn("Use me", payload["instructions"][0])

    def test_runtime_skill_registry_includes_think_with_me_skill(self):
        registry = RuntimeSkillRegistry()

        candidates = registry.query_candidates("think with me about a fuzzy campaign idea")

        self.assertIn("think-with-me", [item["name"] for item in candidates])
        skill = next(item for item in candidates if item["name"] == "think-with-me")
        payload = registry.skill_payload(skill)
        self.assertEqual(payload["name"], "think-with-me")
        self.assertTrue(any("Interview the user relentlessly" in section for section in payload["instructions"]))

    def test_runtime_skill_short_terms_require_token_match(self):
        registry = RuntimeSkillRegistry()

        candidates = registry.query_candidates("think with me about a fuzzy campaign idea")

        self.assertNotIn("air-sql-analyst", [item["name"] for item in candidates])

    def test_chat_sticks_active_runtime_skill_within_session(self):
        llm = ThinkWithMeLLM(plan={"action": "answer_direct", "answer": "Is this what you mean?", "confidence": 0.9})
        store = self.make_store(llm_client=llm)

        first = store.chat(message="think with me about a fuzzy campaign idea", session_id="sticky-think")
        second = store.chat(message="yes dung roi", session_id="sticky-think")

        session = store._get_or_create_chat_session(session_id="sticky-think", user_id="")
        self.assertEqual(session["active_runtime_skill"], "think-with-me")
        self.assertEqual(first["debug"]["runtime_skills_used"], ["think-with-me"])
        self.assertEqual(second["debug"]["runtime_skills_used"], ["think-with-me"])
        self.assertEqual(second["debug"]["runtime_skill_selection_reason"], "using active runtime skill from session: think-with-me")
        self.assertEqual(llm.skill_selector_inputs, [])

    def test_chat_cancel_clears_active_runtime_skill(self):
        llm = ThinkWithMeLLM(plan={"action": "answer_direct", "answer": "Is this what you mean?", "confidence": 0.9})
        store = self.make_store(llm_client=llm)

        store.chat(message="think with me about a fuzzy campaign idea", session_id="sticky-cancel")
        cancelled = store.chat(message="cancel", session_id="sticky-cancel")

        session = store._get_or_create_chat_session(session_id="sticky-cancel", user_id="")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["intent"], "runtime_skill")
        self.assertEqual(session["active_runtime_skill"], "")

    def test_chat_data_question_routes_to_missing_dictionary_flow(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[{"action": "propose_data_query", "answer": "", "payload": {"resolved_message": "RPU tháng 6 theo campaign là bao nhiêu?"}, "confidence": 0.9}]
                ,
                text="Mình thiếu mapping bảng/cột để sinh SQL an toàn.",
            )
        )
        self.teach_rpu(store)

        result = store.chat(message="RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["intent"], "data_sql")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["pending_action_type"], "data_query")
        self.assertTrue(result["debug"]["answer_synthesis_used"])
        self.assertNotIn("pending_action_id", result["answer"])

        confirmed = store.chat(
            message="confirm",
            session_id=result["chat_session_id"],
            pending_action_id=result["pending_action_id"],
        )

        self.assertEqual(confirmed["intent"], "data_sql")
        self.assertEqual(confirmed["status"], "needs_dictionary")
        self.assertIn("mapping bảng/cột", confirmed["answer"])

    def test_chat_vague_data_question_asks_clarification_before_confirmation(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "answer_and_propose_data_query",
                        "answer": "PU là user có phát sinh giao dịch thành công.",
                        "payload": {"resolved_message": "Vậy cho tôi biết một vài số của PU được không?"},
                        "confidence": 0.9,
                    }
                ]
            )
        )
        store.teach_text(text="PU là Paying User, user có phát sinh giao dịch thành công.", stakeholder="BI")

        result = store.chat(message="Vậy cho tôi biết một vài số của PU được không?", session_id="vague-pu")

        self.assertEqual(result["intent"], "data_sql")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(result["pending_action_id"], "")
        self.assertTrue(result["debug"]["answer_synthesis_used"])
        self.assertEqual([item["concept"] for item in result["missing"]], ["time_range", "output_shape"])

    def test_chat_refines_pending_data_query_from_clarification_answer(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "propose_data_query",
                        "answer": "",
                        "payload": {"resolved_message": "Top route thực mua tháng 2 theo provider là gì?"},
                        "confidence": 0.9,
                    }
                ]
            )
        )

        proposed = store.chat(
            message="Top route thực mua tháng 2 theo provider là gì?",
            user_id="quynh",
            session_id="pending-data-refine",
        )
        refined = store.chat(
            message="Xếp hạng theo số giao dịch transID",
            user_id="quynh",
            session_id="pending-data-refine",
        )

        self.assertEqual(refined["status"], "needs_confirmation")
        self.assertEqual(refined["pending_action_id"], proposed["pending_action_id"])
        self.assertEqual(refined["pending_action_type"], "data_query")
        self.assertIn("Top route thực mua", refined["question"])
        self.assertIn("tháng 2", refined["question"])
        self.assertIn("Xếp hạng theo số giao dịch transID", refined["question"])
        self.assertTrue(refined["debug"]["answer_synthesis_used"])
        self.assertNotIn("pending_action_id", refined["answer"])
        self.assertNotIn("pending", refined["answer"].lower())
        self.assertTrue(refined["debug"]["pending_action_refined"])

    def test_chat_answer_synthesis_failure_falls_back_safely(self):
        store = self.make_store(
            llm_client=FailingTextLLM(
                plans=[
                    {
                        "action": "propose_data_query",
                        "answer": "",
                        "payload": {"resolved_message": "RPU tháng 6 theo campaign là bao nhiêu?"},
                        "confidence": 0.9,
                    }
                ]
            )
        )
        self.teach_rpu(store)

        result = store.chat(message="RPU tháng 6 theo campaign là bao nhiêu?", session_id="synthesis-fallback")

        self.assertEqual(result["status"], "needs_confirmation")
        self.assertFalse(result["debug"]["answer_synthesis_used"])
        self.assertEqual(result["debug"]["answer_synthesis_fallback_reason"], "llm_error")
        self.assertNotIn("pending_action_id", result["answer"])

    def test_chat_answer_synthesis_rejects_sql_when_dictionary_missing(self):
        store = self.make_store(llm_client=ViolatingSynthesisLLM())
        session = store._get_or_create_chat_session(session_id="invalid-synthesis", user_id="")

        result = store._finalize_chat_response(
            {
                "status": "needs_dictionary",
                "intent": "data_sql",
                "answer": "Mình hiểu ý câu hỏi, nhưng chưa đủ mapping bảng/cột để sinh SQL an toàn.",
                "question": "PU tháng 2",
                "missing": [{"type": "column_mapping", "concept": "PU", "question": "PU lấy từ bảng/cột nào?"}],
                "debug": {},
            },
            chat_session=session,
            requires_confirmation=False,
        )

        self.assertFalse(result["debug"]["answer_synthesis_used"])
        self.assertEqual(result["debug"]["answer_synthesis_fallback_reason"], "invalid_locked_state")
        self.assertNotIn("SELECT", result["answer"])

    def test_chat_mixed_definition_and_data_requires_data_confirmation(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "answer_and_propose_data_query",
                        "answer": "RPU là Revenue Per User.",
                        "payload": {"resolved_message": "RPU tháng 6 theo campaign bao nhiêu?"},
                        "confidence": 0.9,
                    }
                ]
            )
        )
        self.teach_rpu(store)

        result = store.chat(message="RPU là gì, tháng 6 theo campaign bao nhiêu?", session_id="mixed-data")

        self.assertEqual(result["intent"], "data_sql")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["pending_action_type"], "data_query")
        self.assertIn("Revenue Per User", result["answer"])
        self.assertTrue(result["requires_confirmation"])

    def test_chat_follow_up_data_question_uses_session_context(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {"action": "answer_direct", "answer": "RPU là Revenue Per User.", "confidence": 0.9},
                    {
                        "action": "propose_data_query",
                        "answer": "",
                        "payload": {"resolved_message": "RPU tháng 6 theo campaign bao nhiêu?"},
                        "confidence": 0.9,
                    },
                ]
            )
        )
        self.teach_rpu(store)

        first = store.chat(message="RPU là gì?", user_id="quynh", session_id="ctx-data")
        result = store.chat(message="thế tháng 6 theo campaign bao nhiêu?", user_id="quynh", session_id="ctx-data")

        self.assertEqual(first["status"], "answered")
        self.assertEqual(result["intent"], "data_sql")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["pending_action_type"], "data_query")
        self.assertTrue(result["conversation_context_used"])
        self.assertTrue(result["debug"]["conversation_history_used"])
        self.assertGreaterEqual(result["debug"]["conversation_history_turns"], 2)
        self.assertEqual(result["context_backend"], "local")
        self.assertIn("RPU", result["resolved_question"])

        confirmed = store.chat(
            message="confirm",
            user_id="quynh",
            session_id="ctx-data",
            pending_action_id=result["pending_action_id"],
        )

        self.assertEqual(confirmed["intent"], "data_sql")
        self.assertEqual(confirmed["status"], "needs_dictionary")
        self.assertIn("RPU", confirmed["question"])

    def test_chat_follow_up_comparison_uses_session_context(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {"action": "answer_direct", "answer": "RPU là Revenue Per User.", "confidence": 0.9},
                    {
                        "action": "answer_direct",
                        "answer": "RPU dùng active users, còn ARPPU dùng paying users.",
                        "confidence": 0.9,
                    },
                ]
            )
        )
        self.teach_rpu(store)
        self.teach_arppu(store)

        store.chat(message="RPU là gì?", user_id="quynh", session_id="ctx-compare")
        result = store.chat(message="nó khác ARPPU thế nào?", user_id="quynh", session_id="ctx-compare")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["intent"], "planner_answer")
        self.assertTrue(result["conversation_context_used"])
        self.assertTrue(result["debug"]["conversation_history_used"])
        self.assertIn("ARPPU", result["answer"])
        self.assertIn("paying users", result["answer"])

    def test_chat_follow_up_without_session_context_asks_clarification(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "ask_clarification",
                        "answer": "Bạn đang hỏi tiếp metric hoặc khái niệm nào?",
                        "clarifying_questions": ["Bạn đang hỏi tiếp metric hoặc khái niệm nào?"],
                        "confidence": 0.7,
                    }
                ]
            )
        )
        self.teach_rpu(store)

        result = store.chat(message="thế tháng 6 theo campaign bao nhiêu?", user_id="quynh", session_id="new-session")

        self.assertEqual(result["status"], "needs_clarification")
        self.assertFalse(result["conversation_context_used"])
        self.assertNotIn("RPU", result["resolved_question"])

    def test_chat_planner_receives_conversation_history_from_session_mirror(self):
        llm = CapturingPlannerLLM(plan={"action": "answer_direct", "answer": "ok", "confidence": 0.9})
        store = self.make_store(llm_client=llm)

        store.chat(message="Top route thực mua tháng 2 theo provider", user_id="quynh", session_id="history-pack")
        store.chat(message="Tính theo transID", user_id="quynh", session_id="history-pack")

        history = llm.planner_inputs[-1]["conversation_history"]
        self.assertTrue(any(item["content"] == "Top route thực mua tháng 2 theo provider" for item in history))
        self.assertTrue(any(item["content"] == "Tính theo transID" for item in history))
        self.assertNotIn("recent_turns", llm.planner_inputs[-1])

    def test_chat_hydrates_empty_local_history_from_agentbase_memory(self):
        llm = CapturingPlannerLLM(plan={"action": "recall_conversation", "answer": "Câu đầu là: AOV là gì?", "confidence": 0.9})
        store = self.make_store(
            llm_client=llm,
            chat_context_backend="agentbase",
            chat_context_memory_id="mem-test",
        )
        memory = FakeMemoryEventStore(
            events=[
                {"role": "user", "content": "AOV là gì?", "created_at": "2026-06-12T00:00:00+00:00"},
                {"role": "assistant", "content": "AOV là Average Order Value.", "created_at": "2026-06-12T00:00:01+00:00"},
            ]
        )
        store._resolve_context_store = lambda *, user_id, session_id: ("agentbase", memory, "")

        result = store.chat(
            message="Câu đầu tiên tôi hỏi là gì?",
            user_id="quynh",
            session_id="hydrated-session",
        )

        self.assertEqual(result["status"], "answered")
        self.assertTrue(result["debug"]["memory_hydrated"])
        self.assertFalse(result["debug"]["memory_timeout"])
        self.assertTrue(any(item["content"] == "AOV là gì?" for item in llm.planner_inputs[-1]["conversation_history"]))
        self.assertTrue(any(item["role"] == "user" for item in memory.appended))
        self.assertTrue(any(item["role"] == "assistant" for item in memory.appended))

    def test_chat_memory_timeout_uses_session_mirror_without_hanging(self):
        llm = CapturingPlannerLLM(plan={"action": "answer_direct", "answer": "ok", "confidence": 0.9})
        store = self.make_store(
            llm_client=llm,
            chat_context_backend="agentbase",
            chat_context_memory_id="mem-test",
            chat_memory_timeout_ms=1,
        )
        memory = FakeMemoryEventStore(delay=0.05)
        store._resolve_context_store = lambda *, user_id, session_id: ("agentbase", memory, "")

        started = time.perf_counter()
        result = store.chat(message="Bạn là ai?", user_id="quynh", session_id="timeout-session")
        elapsed = time.perf_counter() - started

        self.assertEqual(result["status"], "answered")
        self.assertLess(elapsed, 0.5)
        self.assertTrue(result["debug"]["memory_timeout"])
        self.assertIn("timeout", " ".join(result["debug"].get("memory_errors", [])))
        self.assertTrue(any(item["content"] == "Bạn là ai?" for item in llm.planner_inputs[-1]["conversation_history"]))

    def test_chat_can_recall_first_question_in_session(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {"action": "answer_direct", "answer": "Mình chưa có đủ context.", "confidence": 0.5},
                    {"action": "answer_direct", "answer": "Mình chưa có đủ context.", "confidence": 0.5},
                    {
                        "action": "recall_conversation",
                        "answer": "Câu hỏi đầu tiên bạn gửi trong session này là: Doanh thu là gì nhỉ?",
                        "confidence": 0.9,
                    },
                ]
            )
        )

        store.chat(message="Doanh thu là gì nhỉ?", user_id="quynhvm", session_id="test-001")
        store.chat(message="Tổng tiền gọi là gì nhỉ?", user_id="quynhvm", session_id="test-001")

        result = store.chat(
            message="Bạn có biết câu hỏi đầu tiên mà tui gửi bạn là gì không?",
            user_id="quynhvm",
            session_id="test-001",
        )

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["intent"], "conversation_recall")
        self.assertIn("Doanh thu là gì nhỉ?", result["answer"])
        self.assertFalse(result["requires_confirmation"])
        self.assertTrue(result["conversation_context_used"])
        self.assertTrue(result["debug"]["conversation_history_used"])

    def test_chat_uses_llm_for_intent_and_answer_when_configured(self):
        store = self.make_store(llm_client=FakeChatLLM(plans=[{"action": "answer_direct", "answer": "RPU là câu trả lời được viết bởi LLM.", "confidence": 0.9}]))
        self.teach_rpu(store)

        result = store.chat(message="RPU là gì?")

        self.assertEqual(result["status"], "answered")
        self.assertTrue(result["debug"]["llm_used"])
        self.assertEqual(result["answer"], "RPU là câu trả lời được viết bởi LLM.")

    def test_chat_general_help_answers_without_knowledge_lookup(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[{"action": "answer_direct", "answer": "Mình là business-knowledge-learning-agent.", "confidence": 0.9}]
            )
        )

        result = store.chat(message="Bạn là ai?")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["intent"], "planner_answer")
        self.assertIn("business-knowledge-learning-agent", result["answer"])
        self.assertEqual(result["used_knowledge_ids"], [])

    def test_chat_forces_teaching_when_user_requests_knowledge_write(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "answer_direct",
                        "answer": "Đã lưu định nghĩa FPU vào từ điển metric.",
                        "confidence": 0.9,
                    }
                ]
            )
        )

        result = store.chat(
            message="Mình muốn lưu định nghĩa FPU là First Paying User vào từ điển metric của team",
            user_id="quynh",
            session_id="force-teach-1",
        )

        self.assertEqual(result["intent"], "teach_knowledge")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["pending_action_type"], "start_teaching")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(store.search_knowledge("FPU"), [])

    def test_chat_blocks_false_knowledge_write_claim_without_commit(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "answer_direct",
                        "answer": "Đã lưu định nghĩa FPU vào từ điển metric của team.",
                        "confidence": 0.9,
                    }
                ]
            )
        )

        result = store.chat(message="Đúng vậy, mình xác nhận", user_id="quynh", session_id="false-save-1")

        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["intent"], "clarification")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(result["pending_action_id"], "")
        self.assertIn("chưa lưu", result["answer"])
        self.assertTrue(result["debug"]["knowledge_write_invariant_blocked"])
        self.assertEqual(store.search_knowledge("FPU"), [])

    def test_chat_can_teach_confirmed_knowledge(self):
        # Sau khi user xac nhan MOT lan, neu dinh nghia da du thi agent luu thang,
        # khong tao them buoc xac nhan commit_teaching nua.
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "propose_teaching",
                        "answer": "Bạn nhắn 'ok' để mình lưu định nghĩa này vào từ điển nhé.",
                        "payload": {"message": "AOV là Average Order Value, giá trị đơn hàng trung bình."},
                        "confidence": 0.9,
                    },
                ]
            )
        )
        self.teach_rpu(store)

        proposed = store.chat(
            message="AOV là Average Order Value, giá trị đơn hàng trung bình.",
            user_id="quynh",
            session_id="teach-chat-1",
        )

        self.assertEqual(proposed["intent"], "teach_knowledge")
        self.assertEqual(proposed["status"], "needs_confirmation")
        self.assertEqual(proposed["chat_session_id"], "teach-chat-1")
        self.assertEqual(proposed["pending_action_type"], "start_teaching")
        self.assertEqual(store.search_knowledge("AOV"), [])

        # Mot lan xac nhan -> luu thang, khong con buoc xac nhan thu hai.
        confirmed = store.chat(
            message="ok",
            user_id="quynh",
            session_id=proposed["chat_session_id"],
            pending_action_id=proposed["pending_action_id"],
        )

        self.assertEqual(confirmed["intent"], "teach_knowledge")
        self.assertEqual(confirmed["status"], "committed")
        self.assertFalse(confirmed["requires_confirmation"])
        self.assertEqual(confirmed["pending_action_type"], "")
        self.assertEqual(store.search_knowledge("AOV")[0]["name"], "AOV")

    def test_chat_new_pending_replaces_previous_pending_action(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "propose_teaching",
                        "answer": "Bạn confirm mình bắt đầu teaching session từ nội dung này chứ?",
                        "payload": {"message": "AOV là Average Order Value."},
                        "confidence": 0.9,
                    },
                    {
                        "action": "propose_data_query",
                        "answer": "",
                        "payload": {"resolved_message": "RPU tháng 6 theo campaign là bao nhiêu?"},
                        "confidence": 0.9,
                    },
                ]
            )
        )
        self.teach_rpu(store)

        teach = store.chat(message="AOV là Average Order Value.", session_id="mixed-session")
        data = store.chat(message="RPU tháng 6 theo campaign là bao nhiêu?", session_id="mixed-session")

        self.assertEqual(teach["pending_action_type"], "start_teaching")
        self.assertEqual(data["pending_action_type"], "data_query")
        self.assertNotEqual(teach["pending_action_id"], data["pending_action_id"])

        session = store._get_or_create_chat_session(session_id="mixed-session", user_id="")
        pending = store._pending_chat_actions(session)
        self.assertEqual([action["id"] for action in pending], [data["pending_action_id"]])
        old_action = session["pending_actions"][teach["pending_action_id"]]
        self.assertEqual(old_action["status"], "cancelled")
        self.assertEqual(old_action["cancel_reason"], "replaced_by_new_pending_action")

        confirmed = store.chat(message="confirm", session_id="mixed-session")

        self.assertEqual(confirmed["intent"], "data_sql")
        self.assertNotEqual(confirmed["status"], "needs_clarification")

    def test_chat_pending_status_uses_session_state_not_llm(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "propose_data_query",
                        "answer": "",
                        "payload": {"resolved_message": "Top route thực mua tháng 2 theo provider"},
                        "confidence": 0.9,
                    },
                    {
                        "action": "answer_direct",
                        "answer": "LLM should not answer pending status.",
                        "confidence": 0.9,
                    },
                ]
            )
        )

        proposed = store.chat(message="Top route thực mua tháng 2 theo provider", session_id="pending-status")
        status = store.chat(message="Có peding data nào đang chờ không?", session_id="pending-status")

        self.assertEqual(proposed["pending_action_type"], "data_query")
        self.assertEqual(status["intent"], "pending_status")
        self.assertIn("Top route thực mua tháng 2 theo provider", status["answer"])
        self.assertEqual(status["pending_action_id"], proposed["pending_action_id"])
        self.assertFalse(status["debug"]["llm_used"])

    def test_chat_confirm_fast_path_does_not_call_planner_again(self):
        llm = CapturingPlannerLLM(
            plan={
                "action": "propose_data_query",
                "answer": "",
                "payload": {"resolved_message": "Top route thực mua tháng 2 theo provider"},
                "confidence": 0.9,
            }
        )
        store = self.make_store(llm_client=llm)

        proposed = store.chat(message="Top route thực mua tháng 2 theo provider", session_id="confirm-fast-path")
        planner_calls_after_proposal = len(llm.planner_inputs)
        synthesis_calls_after_proposal = len(llm.text_inputs)
        confirmed = store.chat(
            message="confirm",
            session_id="confirm-fast-path",
            pending_action_id=proposed["pending_action_id"],
        )

        self.assertEqual(planner_calls_after_proposal, 1)
        self.assertEqual(len(llm.planner_inputs), planner_calls_after_proposal)
        self.assertEqual(len(llm.text_inputs), synthesis_calls_after_proposal)
        self.assertEqual(confirmed["intent"], "data_sql")
        self.assertIn(confirmed["status"], {"needs_knowledge", "needs_dictionary", "needs_example", "sql_draft"})

    def test_chat_cancel_clears_active_pending_action(self):
        store = self.make_store(
            llm_client=FakeChatLLM(
                plans=[
                    {
                        "action": "propose_data_query",
                        "answer": "",
                        "payload": {"resolved_message": "Top route thực mua tháng 2 theo provider"},
                        "confidence": 0.9,
                    }
                ]
            )
        )

        proposed = store.chat(message="Top route thực mua tháng 2 theo provider", session_id="cancel-pending")
        cancelled = store.chat(message="cancel tất cả pending", session_id="cancel-pending")
        status = store.chat(message="Có pending nào đang chờ không?", session_id="cancel-pending")

        self.assertEqual(proposed["pending_action_type"], "data_query")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["pending_action_id"], "")
        self.assertEqual(status["intent"], "pending_status")
        self.assertIn("Không có pending action", status["answer"])
        self.assertEqual(status["session_state"], "idle")


if __name__ == "__main__":
    unittest.main()
