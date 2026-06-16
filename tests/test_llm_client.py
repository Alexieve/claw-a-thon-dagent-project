import unittest

import agent_core.llm as llm_module
from agent_core.llm import AgentLLMClient


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class _FakeHTTPClient:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        return _FakeResponse(self._content)


class LLMClientNewlineTest(unittest.TestCase):
    def _make_client(self, content: str) -> AgentLLMClient:
        client = AgentLLMClient()
        client.api_key = "test-key"
        client.base_url = "https://example.test/v1"
        client.model = "test-model"
        fake = _FakeHTTPClient(content)
        # Ep _complete dung fake HTTP client thay vi goi mang that.
        self._orig_get = llm_module._get_http_client
        llm_module._get_http_client = lambda timeout: fake
        self.addCleanup(lambda: setattr(llm_module, "_get_http_client", self._orig_get))
        return client

    def test_complete_text_preserves_newlines(self):
        markdown = "## Tiêu đề\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```sql\nSELECT 1\n```"
        client = self._make_client(markdown)
        out = client.complete_text(system="s", user="u")
        # Bug cu: normalize_text flatten het \n -> mot dong. Gio phai giu xuong dong.
        self.assertGreater(out.count("\n"), 4)
        self.assertIn("| A | B |", out)
        self.assertIn("```sql", out)

    def test_complete_text_strips_outer_whitespace(self):
        client = self._make_client("\n\n  Xin chào\n\n")
        self.assertEqual(client.complete_text(system="s", user="u"), "Xin chào")

    def test_complete_json_still_parses_with_newlines(self):
        client = self._make_client('{\n  "action": "answer_direct",\n  "answer": "ok"\n}')
        parsed = client.complete_json(system="s", user="u")
        self.assertEqual(parsed["action"], "answer_direct")


if __name__ == "__main__":
    unittest.main()
