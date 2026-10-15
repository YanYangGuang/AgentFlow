import os
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import ModelProviderCredentialRecord
from app.services.provider_config import decrypt_secret
from app.services.provider_config import safe_base_url
from app.services.provider_runtime import _validate_target
from app.services.live_model import chat_completion


class ProviderConfigurationTests(unittest.TestCase):
    def test_save_encrypt_and_persist_connection_status_then_invalidate_on_change(self):
        key = Fernet.generate_key().decode("ascii")
        with patch.dict(os.environ, {
            "AGENTFLOW_CREDENTIAL_ENCRYPTION_KEY": key,
            "AGENTFLOW_ENABLE_LIVE_EXECUTION": "true",
            "AGENTFLOW_LLM_API_KEY": "",
        }, clear=False), TestClient(app) as client:
            directory = client.get("/api/v1/models/providers")
            self.assertEqual(directory.status_code, 200)
            openai = next(item for item in directory.json() if item["code"] == "openai")
            self.assertFalse(openai["configured"])
            self.assertEqual(openai["base_url"], "https://api.openai.com/v1")

            secret = "provider-test-secret-never-return-this"
            saved = client.put("/api/v1/models/providers/openai", json={
                "api_base_url": "https://api.openai.com/v1", "default_model_id": "gpt-test", "api_key": secret,
            })
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertTrue(saved.json()["configured"])
            self.assertTrue(saved.json()["credential_saved"])
            self.assertNotIn(secret, saved.text)
            with SessionLocal() as db:
                credential = db.query(ModelProviderCredentialRecord).filter_by(provider_id="provider_openai").one()
                self.assertNotIn(secret, credential.encrypted_secret)

            with patch("app.main.verify_provider", new=AsyncMock(return_value={"ok": True, "message": "供应商模型接口访问成功。", "models_available": 4})):
                tested = client.post("/api/v1/models/providers/openai/test", json={
                    "api_base_url": "https://api.openai.com/v1", "default_model_id": "gpt-test",
                })
            self.assertEqual(tested.status_code, 200, tested.text)
            self.assertTrue(tested.json()["persisted"])
            persisted = next(item for item in client.get("/api/v1/models/providers").json() if item["code"] == "openai")
            self.assertEqual(persisted["last_test_status"], "connected")
            self.assertIsNotNone(persisted["last_test_at"])

            with patch("app.main.verify_provider", new=AsyncMock(side_effect=RuntimeError("凭据无权访问该接口（HTTP 403）。"))):
                failed = client.post("/api/v1/models/providers/openai/test", json={
                    "api_base_url": "https://api.openai.com/v1", "default_model_id": "gpt-test",
                })
            self.assertEqual(failed.status_code, 200)
            self.assertEqual(failed.json()["status"], "connection_failed")
            failed_state = next(item for item in client.get("/api/v1/models/providers").json() if item["code"] == "openai")
            self.assertEqual(failed_state["last_test_status"], "connection_failed")

            with patch("app.main.verify_provider", new=AsyncMock(return_value={"ok": True, "message": "ok", "models_available": 2})):
                unsaved = client.post("/api/v1/models/providers/openai/test", json={
                    "api_base_url": "https://api.openai.com/v2", "default_model_id": "gpt-test",
                })
            self.assertFalse(unsaved.json()["persisted"])
            still_failed = next(item for item in client.get("/api/v1/models/providers").json() if item["code"] == "openai")
            self.assertEqual(still_failed["last_test_status"], "connection_failed")

            changed = client.put("/api/v1/models/providers/openai", json={
                "api_base_url": "https://api.openai.com/v1", "default_model_id": "gpt-next",
            })
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(changed.json()["last_test_status"], "not_tested")
            self.assertTrue(changed.json()["configured"])
            self.assertTrue(changed.json()["credential_saved"])
            self.assertNotIn(secret, changed.text)
            with SessionLocal() as db:
                credential = db.query(ModelProviderCredentialRecord).filter_by(provider_id="provider_openai").one()
                self.assertEqual(decrypt_secret(credential), secret)

            with patch("app.main.fetch_models", new=AsyncMock(return_value=[{"id": "gpt-next", "name": "GPT Next", "context_length": None, "source": "provider"}])):
                catalog = client.get("/api/v1/models/providers/openai/models")
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertEqual(catalog.json()[0]["id"], "gpt-next")

            with patch("app.services.provider_runtime.complete_provider", new=AsyncMock(return_value={"text": "ok", "model": "gpt-next", "tokens": 2})) as invoke:
                completion = asyncio.run(chat_completion("test prompt"))
            self.assertEqual(completion["text"], "ok")
            self.assertEqual(invoke.await_args.args[:4], ("openai", "openai-compatible", "https://api.openai.com/v1", secret))

            rejected = client.put("/api/v1/models/providers/openai", json={
                "api_base_url": "https://api.openai.com/v1", "default_model_id": "gpt-test", "api_key": secret * 200,
            })
            self.assertEqual(rejected.status_code, 422)
            self.assertNotIn(secret, rejected.text)

    def test_rejects_insecure_and_private_provider_targets(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            safe_base_url("http://provider.example/v1", "openai-compatible")
        with self.assertRaisesRegex(ValueError, "内网"):
            safe_base_url("https://127.0.0.1/v1", "openai-compatible")
        private_dns = [(2, 1, 6, "", ("10.20.30.40", 443))]
        with patch("app.services.provider_runtime.socket.getaddrinfo", return_value=private_dns):
            with self.assertRaisesRegex(RuntimeError, "内网"):
                _validate_target("https://public-looking.example/v1")


if __name__ == "__main__":
    unittest.main()
