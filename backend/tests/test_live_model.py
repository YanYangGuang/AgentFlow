import asyncio
import os
import unittest
from unittest.mock import patch

import httpx

from app.services.live_model import chat_completion, chat_completions_url, model_settings


class LiveModelConfigurationTests(unittest.TestCase):
    def test_root_and_complete_openrouter_urls_are_not_double_joined(self):
        self.assertEqual(
            chat_completions_url("https://openrouter.ai/api/v1"),
            "https://openrouter.ai/api/v1/chat/completions",
        )
        self.assertEqual(
            chat_completions_url("https://openrouter.ai/api/v1/chat/completions"),
            "https://openrouter.ai/api/v1/chat/completions",
        )

    def test_true_string_enables_runtime_flag_without_exposing_key(self):
        with patch.dict(os.environ, {
            "AGENTFLOW_ENABLE_LIVE_EXECUTION": "true",
            "AGENTFLOW_LLM_API_KEY": "test-only-secret",
        }, clear=False):
            settings = model_settings()
        self.assertTrue(settings["live_enabled"])
        self.assertTrue(settings["configured"])
        self.assertNotIn("test-only-secret", str(settings))

    def test_missing_key_fails_before_any_network_request(self):
        with patch.dict(os.environ, {"AGENTFLOW_LLM_API_KEY": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "未配置真实模型 API Key"):
                asyncio.run(chat_completion("test"))

    def test_401_is_reported_without_returning_provider_body_or_key(self):
        observed = {}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def post(self, url, *, headers, json):
                observed.update(url=url, headers=headers, body=json)
                return httpx.Response(401, request=httpx.Request("POST", url), text="secret provider diagnostic")

        with patch.dict(os.environ, {
            "AGENTFLOW_LLM_API_KEY": "test-only-secret",
            "AGENTFLOW_LLM_BASE_URL": "https://openrouter.ai/api/v1/chat/completions",
        }, clear=False), patch("app.services.live_model.httpx.AsyncClient", return_value=FakeClient()):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as raised:
                asyncio.run(chat_completion("test"))

        self.assertEqual(observed["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(observed["headers"]["Authorization"], "Bearer test-only-secret")
        self.assertNotIn("test-only-secret", str(raised.exception))
        self.assertNotIn("secret provider diagnostic", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
