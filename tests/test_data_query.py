import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from agent_core.data_warehouse import _json_safe, validate_readonly_select, warehouse_schema_summary
from api_contracts import AgentApiRouter
from knowledge_store import KnowledgeParser, KnowledgeStore


SQL_OK = (
    "SELECT campaign_name, SUM(payments.amount) AS revenue\n"
    "FROM payments JOIN campaigns ON payments.campaign_id = campaigns.id\n"
    "WHERE payments.amount > 0\nGROUP BY 1 ORDER BY 1 LIMIT 100"
)
SQL_REPAIRED = SQL_OK + "\n-- fixed"


class FakeDataLLM:
    """Trả SQL cho prompt sinh-SQL/repair; điều khiển planner qua `plans`."""

    def __init__(self, *, plans=None, sql=SQL_OK, repaired_sql=None, text="Tóm tắt kết quả."):
        self.plans = list(plans or [])
        self.sql = sql
        self.repaired_sql = repaired_sql
        self.text = text
        self.gen_calls = 0
        self.repair_calls = 0
        self.gen_questions = []  # câu hỏi mà SQL-generator nhận được

    def configured(self):
        return True

    def complete_json(self, *, system, user, temperature=0, model=None):
        import json as _json

        if "A PostgreSQL SELECT query failed" in system:
            self.repair_calls += 1
            return {"sql": self.repaired_sql or self.sql, "explanation": ["repaired"]}
        if "runnable PostgreSQL" in system:
            self.gen_calls += 1
            try:
                self.gen_questions.append(_json.loads(user).get("question"))
            except Exception:
                self.gen_questions.append(None)
            return {"sql": self.sql, "explanation": ["llm postgres sql"], "answer": "ok"}
        if "select runtime skills" in system:
            return {"selected_skills": [], "reason": ""}
        if "action planner" in system:
            if self.plans:
                return self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]
            return {"action": "noop"}
        return {}

    def complete_text(self, *, system, user, temperature=0.2, model=None):
        return self.text


class FakeWarehouse:
    def __init__(self, *, results=None, max_rows=1000):
        self.max_rows = max_rows
        self.results = list(results or [])
        self.calls = []

    def execute_readonly(self, sql, *, max_rows=None, timeout_ms=None):
        self.calls.append(sql)
        if self.results:
            return self.results.pop(0)
        return {
            "ok": True,
            "error": "",
            "columns": ["campaign_name", "revenue"],
            "rows": [{"campaign_name": "Tet", "revenue": 100}],
            "row_count": 1,
            "truncated": False,
            "elapsed_ms": 1,
        }


def ok_result(rows=None):
    rows = rows if rows is not None else [{"campaign_name": "Tet", "revenue": 100}]
    return {
        "ok": True,
        "error": "",
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows,
        "row_count": len(rows),
        "truncated": False,
        "elapsed_ms": 2,
    }


def err_result(message):
    return {"ok": False, "error": message, "columns": [], "rows": [], "row_count": 0, "truncated": False, "elapsed_ms": 1}


class ValidatorTest(unittest.TestCase):
    def test_accepts_select_and_with(self):
        self.assertTrue(validate_readonly_select("SELECT 1")[0])
        self.assertTrue(validate_readonly_select("  with x as (select 1) select * from x")[0])
        self.assertTrue(validate_readonly_select("-- comment\nSELECT count(*) FROM payment_air")[0])

    def test_rejects_dml_ddl(self):
        for bad in [
            "DELETE FROM payment_air",
            "UPDATE payment_air SET amount=0",
            "INSERT INTO payment_air VALUES (1)",
            "DROP TABLE search_air",
            "TRUNCATE search_air",
            "ALTER TABLE search_air ADD COLUMN x int",
        ]:
            self.assertFalse(validate_readonly_select(bad)[0], bad)

    def test_rejects_multi_statement_and_writable_cte(self):
        self.assertFalse(validate_readonly_select("SELECT 1; SELECT 2")[0])
        self.assertFalse(
            validate_readonly_select("WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x")[0]
        )

    def test_rejects_empty(self):
        self.assertFalse(validate_readonly_select("")[0])
        self.assertFalse(validate_readonly_select("   -- only comment")[0])

    def test_trailing_semicolon_is_fine(self):
        self.assertTrue(validate_readonly_select("SELECT 1;")[0])


class JsonSafeTest(unittest.TestCase):
    def test_converts_temporal_and_decimal(self):
        self.assertEqual(_json_safe(datetime(2026, 2, 2, 19, 42, 55)), "2026-02-02T19:42:55")
        self.assertEqual(_json_safe(date(2026, 2, 3)), "2026-02-03")
        self.assertEqual(_json_safe(Decimal("1413000")), 1413000.0)
        self.assertEqual(_json_safe(None), None)
        self.assertEqual(_json_safe("SGN"), "SGN")

    def test_schema_summary_has_both_tables(self):
        summary = warehouse_schema_summary()
        self.assertIn("payment_air(", summary)
        self.assertIn("search_air(", summary)
        self.assertIn("reqdate TIMESTAMP", summary)


class RunDataQueryTest(unittest.TestCase):
    def make_store(self, *, llm_client, data_warehouse=None, new_database_url="") -> KnowledgeStore:
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
            parser=KnowledgeParser(),
            llm_client=llm_client,
            data_warehouse=data_warehouse,
            new_database_url=new_database_url,
        )
        store.bootstrap()
        return store

    def teach_rpu(self, store):
        store.teach_text(
            text="RPU là Revenue Per User, doanh thu trung bình trên mỗi active user. Công thức total revenue / active users.",
            stakeholder="Finance",
            team="Revenue",
        )

    def add_dictionary(self, store):
        store.add_data_dictionary(
            table="payments",
            description="Bảng giao dịch thanh toán",
            columns=[
                {"name": "amount", "business_meaning": "Doanh thu", "data_type": "numeric", "aliases": ["revenue", "gmv"]},
                {"name": "user_id", "business_meaning": "User giao dịch", "data_type": "text", "aliases": ["user", "active user"]},
                {"name": "campaign_id", "business_meaning": "Campaign", "data_type": "text", "aliases": ["campaign"]},
            ],
            relationships=[{"from": "payments.campaign_id", "to": "campaigns.id", "type": "many_to_one"}],
            owner="data-team",
        )
        store.add_data_dictionary(
            table="campaigns",
            description="Bảng campaign",
            columns=[
                {"name": "id", "business_meaning": "Khóa campaign", "data_type": "text", "aliases": ["campaign id"]},
                {"name": "campaign_name", "business_meaning": "Tên campaign", "data_type": "text", "aliases": ["campaign"]},
            ],
            owner="data-team",
        )

    def test_executes_and_returns_rows(self):
        wh = FakeWarehouse(results=[ok_result([{"campaign_name": "Tet", "revenue": 100}])])
        store = self.make_store(llm_client=FakeDataLLM(), data_warehouse=wh)
        self.teach_rpu(store)
        self.add_dictionary(store)

        result = store.run_data_query("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "query_result")
        self.assertEqual(result["sql"], SQL_OK)
        self.assertEqual(result["columns"], ["campaign_name", "revenue"])
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(len(wh.calls), 1)
        self.assertTrue(result["answer"])

    def test_needs_dictionary_does_not_execute(self):
        wh = FakeWarehouse()
        store = self.make_store(llm_client=FakeDataLLM(), data_warehouse=wh)
        self.teach_rpu(store)  # knowledge nhưng KHÔNG có dictionary

        result = store.run_data_query("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "needs_dictionary")
        self.assertEqual(result["sql"], "")
        self.assertEqual(wh.calls, [])

    def test_repairs_once_on_execution_error(self):
        wh = FakeWarehouse(results=[err_result("column reqdate does not exist"), ok_result([{"c": 5}])])
        llm = FakeDataLLM(repaired_sql=SQL_REPAIRED)
        store = self.make_store(llm_client=llm, data_warehouse=wh)
        self.teach_rpu(store)
        self.add_dictionary(store)

        result = store.run_data_query("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "query_result")
        self.assertEqual(result["sql"], SQL_REPAIRED)
        self.assertEqual(len(wh.calls), 2)
        self.assertEqual(llm.repair_calls, 1)

    def test_query_error_when_repair_also_fails(self):
        wh = FakeWarehouse(results=[err_result("boom1"), err_result("boom2")])
        store = self.make_store(llm_client=FakeDataLLM(repaired_sql=SQL_REPAIRED), data_warehouse=wh)
        self.teach_rpu(store)
        self.add_dictionary(store)

        result = store.run_data_query("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "query_error")
        self.assertIn("boom2", result["query_error"])
        self.assertEqual(result["row_count"], 0)

    def test_sql_only_when_no_warehouse(self):
        store = self.make_store(llm_client=FakeDataLLM(), data_warehouse=None, new_database_url="")
        self.teach_rpu(store)
        self.add_dictionary(store)

        result = store.run_data_query("RPU tháng 6 theo campaign là bao nhiêu?")

        self.assertEqual(result["status"], "sql_only")
        self.assertEqual(result["sql"], SQL_OK)
        self.assertIn("NEW_DATABASE_URL", result["query_error"])

    def test_query_data_action_routes_through_router(self):
        wh = FakeWarehouse(results=[ok_result([{"campaign_name": "Tet", "revenue": 100}])])
        store = self.make_store(llm_client=FakeDataLLM(), data_warehouse=wh)
        self.teach_rpu(store)
        self.add_dictionary(store)
        router = AgentApiRouter(store)

        resp = router.dispatch(
            {"action": "query_data", "question": "RPU tháng 6 theo campaign là bao nhiêu?"},
            SimpleNamespace(user_id="u", session_id="s"),
        )

        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["result"]["status"], "query_result")
        self.assertEqual(resp["result"]["row_count"], 1)

    def test_chat_confirm_data_query_executes_and_returns_rows(self):
        plan = {
            "action": "propose_data_query",
            "answer": "",
            "payload": {"resolved_message": "RPU tháng 6 theo campaign là bao nhiêu?"},
            "confidence": 0.9,
        }
        wh = FakeWarehouse(results=[ok_result([{"campaign_name": "Tet", "revenue": 100}])])
        store = self.make_store(llm_client=FakeDataLLM(plans=[plan]), data_warehouse=wh)
        self.teach_rpu(store)
        self.add_dictionary(store)

        proposed = store.chat(message="RPU tháng 6 theo campaign là bao nhiêu?")
        self.assertEqual(proposed["status"], "needs_confirmation")
        self.assertEqual(proposed["pending_action_type"], "data_query")

        confirmed = store.chat(
            message="confirm",
            session_id=proposed["chat_session_id"],
            pending_action_id=proposed["pending_action_id"],
        )

        self.assertEqual(confirmed["intent"], "data_sql")
        self.assertEqual(confirmed["status"], "query_result")
        self.assertEqual(confirmed["row_count"], 1)
        self.assertEqual(confirmed["sql"], SQL_OK)
        self.assertTrue(confirmed["rows"])


class RefinementConfirmationRegressionTest(RunDataQueryTest):
    """Bug test_004: reply xác nhận mơ hồ làm mất câu hỏi gốc + lặp confirm."""

    DATA_Q = "RPU tháng 6 theo campaign là bao nhiêu?"

    def test_merge_refinement_keeps_original_when_vague(self):
        store = self.make_store(llm_client=FakeDataLLM())
        merged = store._merge_data_query_refinement(
            previous_message=self.DATA_Q, refinement="Chắc chung chung vậy là được rồi"
        )
        self.assertEqual(merged, self.DATA_Q)  # KHÔNG bị ghi đè bởi reply mơ hồ

    def test_merge_refinement_appends_structured_detail(self):
        store = self.make_store(llm_client=FakeDataLLM())
        merged = store._merge_data_query_refinement(previous_message="RPU theo campaign", refinement="tháng 6")
        self.assertIn("RPU theo campaign", merged)
        self.assertIn("tháng 6", merged)

    def test_is_chat_confirmation_recognizes_acceptance_phrases(self):
        store = self.make_store(llm_client=FakeDataLLM())
        for phrase in [
            "Chắc chung chung vậy là được rồi",
            "Oke, lấy data giúp mình nhé",
            "lấy số liệu giúp mình",
            "chạy query đi",
            "vậy được rồi",
        ]:
            self.assertTrue(store._is_chat_confirmation(phrase), phrase)
        # Câu hỏi clarification KHÔNG được coi là confirm.
        self.assertFalse(store._is_chat_confirmation("Vậy cho tôi biết một vài số của PU được không?"))

    def test_confirm_runs_on_original_question_not_acceptance_phrase(self):
        plan = {
            "action": "propose_data_query",
            "answer": "",
            "payload": {"resolved_message": self.DATA_Q},
            "confidence": 0.9,
        }
        wh = FakeWarehouse(results=[ok_result([{"campaign_name": "Tet", "revenue": 100}])])
        llm = FakeDataLLM(plans=[plan])
        store = self.make_store(llm_client=llm, data_warehouse=wh)
        self.teach_rpu(store)
        self.add_dictionary(store)

        proposed = store.chat(message=self.DATA_Q)
        self.assertEqual(proposed["status"], "needs_confirmation")

        # Reply xác nhận mơ hồ -> phải confirm + chạy trên CÂU HỎI GỐC, không phải reply.
        confirmed = store.chat(
            message="Chắc chung chung vậy là được rồi",
            session_id=proposed["chat_session_id"],
            pending_action_id=proposed["pending_action_id"],
        )
        self.assertEqual(confirmed["status"], "query_result")
        self.assertEqual(confirmed["row_count"], 1)
        self.assertEqual(llm.gen_questions[-1], self.DATA_Q)

    def test_clarification_gate_uses_recent_context_not_just_current_message(self):
        # Lượt 1 planner hỏi clarify (chưa tạo pending) dù câu hỏi đã đủ thời gian + grain.
        # Lượt 2 user trả lời ngắn KHÔNG có thời gian -> trước đây bị hỏi lại (vòng lặp);
        # sau fix: gate xét cả context gần đây nên tạo pending để confirm.
        plans = [
            {"action": "ask_clarification", "answer": "Bạn muốn lọc gì thêm không?", "confidence": 0.9},
            {"action": "propose_data_query", "answer": "", "payload": {"resolved_message": "thế nhé"}, "confidence": 0.9},
        ]
        store = self.make_store(llm_client=FakeDataLLM(plans=plans))
        self.teach_rpu(store)
        self.add_dictionary(store)

        t1 = store.chat(message="RPU tháng 6 theo campaign là bao nhiêu?", session_id="ctx-clar")
        self.assertEqual(t1["status"], "needs_clarification")
        self.assertEqual(t1.get("pending_action_id", ""), "")

        t2 = store.chat(message="thế nhé", session_id="ctx-clar")
        self.assertEqual(t2["status"], "needs_confirmation")
        self.assertEqual(t2["pending_action_type"], "data_query")

    def test_vague_followup_resolved_via_conversation_context(self):
        # Bug test_005: follow-up mơ hồ ("phân tích sâu hơn") không có term air-data.
        # Không context -> needs_dictionary. Có context (nhắc RPU/campaign) -> retrieve được -> chạy.
        wh = FakeWarehouse(results=[ok_result([{"x": 1}])])
        store = self.make_store(llm_client=FakeDataLLM(), data_warehouse=wh)
        self.teach_rpu(store)
        self.add_dictionary(store)

        no_ctx = store.run_data_query("phân tích sâu hơn đi")
        self.assertEqual(no_ctx["status"], "needs_dictionary")

        with_ctx = store.run_data_query(
            "phân tích sâu hơn đi",
            conversation_text="user: RPU tháng 6 theo campaign là bao nhiêu? assistant: kết quả RPU theo campaign",
        )
        self.assertEqual(with_ctx["status"], "query_result")
        self.assertEqual(with_ctx["sql"], SQL_OK)

    def test_acceptance_without_explicit_id_still_confirms(self):
        plan = {
            "action": "propose_data_query",
            "answer": "",
            "payload": {"resolved_message": self.DATA_Q},
            "confidence": 0.9,
        }
        wh = FakeWarehouse(results=[ok_result([{"d": 1}])])
        llm = FakeDataLLM(plans=[plan])
        store = self.make_store(llm_client=llm, data_warehouse=wh)
        self.teach_rpu(store)
        self.add_dictionary(store)

        proposed = store.chat(message=self.DATA_Q)
        self.assertEqual(proposed["status"], "needs_confirmation")
        # Không gửi pending_action_id, chỉ gửi câu chấp nhận tự nhiên.
        confirmed = store.chat(message="lấy data giúp mình nhé", session_id=proposed["chat_session_id"])
        self.assertEqual(confirmed["status"], "query_result")
        self.assertEqual(llm.gen_questions[-1], self.DATA_Q)


if __name__ == "__main__":
    unittest.main()
