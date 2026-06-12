import unittest
from types import SimpleNamespace

from api_contracts import AgentApiRouter


class FakeStore:
    def __init__(self) -> None:
        self.chat_calls = []

    def chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        message = kwargs.get("message", "")
        if message == "needs confirm":
            return {
                "status": "needs_confirmation",
                "intent": "data_sql",
                "answer": "Ban confirm minh xu ly cau hoi data nay chu?",
                "question": "RPU thang 6 theo campaign",
                "chat_session_id": kwargs.get("session_id") or "chat_1",
                "requires_confirmation": True,
                "pending_action_id": "act_1",
                "pending_action_type": "data_query",
            }
        if message == "confirm":
            return {
                "status": "needs_dictionary",
                "intent": "data_sql",
                "answer": "Can bo sung mapping bang/cot.",
                "question": "RPU thang 6 theo campaign",
                "chat_session_id": kwargs.get("session_id") or "chat_1",
                "requires_confirmation": False,
                "pending_action_id": "",
                "pending_action_type": "",
            }
        return {
            "status": "answered",
            "intent": "planner_answer",
            "answer": "RPU la Revenue Per User.",
            "question": message,
            "chat_session_id": kwargs.get("session_id") or "chat_1",
        }

    def search_knowledge(self, *, query):
        return [{"id": "kn_1", "name": query}]

    def storage_status(self):
        return {"backend": "json", "database_configured": False}


class AgentApiRouterTest(unittest.TestCase):
    def make_router(self):
        return AgentApiRouter(FakeStore())

    def make_context(self, session_id="ctx-session"):
        return SimpleNamespace(user_id="ctx-user", session_id=session_id)

    def test_unknown_action_returns_standard_error_object(self):
        response = self.make_router().dispatch({"action": "missing_action"}, self.make_context())

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"]["code"], "unknown_action")
        self.assertIn("details", response["error"])
        self.assertNotIn("result", response)

    def test_chat_response_uses_v2_envelope_and_normalized_shape(self):
        response = self.make_router().dispatch(
            {"action": "chat", "message": "RPU la gi?", "session_id": "chat-a"},
            self.make_context(),
        )

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["session_id"], "ctx-session")
        result = response["result"]
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"], "RPU la Revenue Per User.")
        self.assertEqual(result["chat_session_id"], "chat-a")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(result["pending_action"], {"id": "", "type": "", "status": "", "confirm_options": []})
        self.assertIn("debug", result)

    def test_needs_confirmation_includes_pending_action_contract(self):
        response = self.make_router().dispatch(
            {"action": "chat", "message": "needs confirm", "session_id": "chat-a"},
            self.make_context(),
        )

        result = response["result"]
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["pending_action_id"], "act_1")
        self.assertEqual(result["pending_action_type"], "data_query")
        self.assertEqual(result["confirm_options"], ["confirm", "cancel"])
        self.assertEqual(
            result["pending_action"],
            {"id": "act_1", "type": "data_query", "status": "pending", "confirm_options": ["confirm", "cancel"]},
        )

    def test_confirm_flow_keeps_session_and_clears_pending_action(self):
        router = self.make_router()
        router.dispatch({"action": "chat", "message": "needs confirm", "session_id": "chat-a"}, self.make_context())

        response = router.dispatch(
            {
                "action": "chat",
                "message": "confirm",
                "session_id": "chat-a",
                "pending_action_id": "act_1",
            },
            self.make_context(),
        )

        self.assertEqual(response["result"]["status"], "needs_dictionary")
        self.assertFalse(response["result"]["requires_confirmation"])
        self.assertEqual(response["result"]["pending_action_id"], "")
        self.assertEqual(response["result"]["pending_action"]["status"], "")

    def test_backward_payload_without_action_routes_message_to_chat(self):
        router = self.make_router()
        response = router.dispatch({"message": "RPU la gi?", "session_id": "chat-a"}, self.make_context())

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["result"]["status"], "answered")
        self.assertEqual(router.store.chat_calls[0]["message"], "RPU la gi?")


if __name__ == "__main__":
    unittest.main()
