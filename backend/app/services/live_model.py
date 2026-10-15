"""Live model adapter using persistent provider settings with legacy environment fallback."""
import os
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import dotenv_values
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

logger = logging.getLogger("agentflow.model")

_project_root = Path(__file__).resolve().parents[3]
_process_env_keys = set(os.environ)
_local_env: dict[str, str] = {}
for _env_path in (_project_root / "backend" / ".env", _project_root / ".env"):
    for _name, _value in dotenv_values(_env_path).items():
        if _value:
            _local_env[_name] = _value
for _name, _value in _local_env.items():
    if _name not in _process_env_keys:
        os.environ[_name] = _value


def model_settings(db=None) -> dict[str, Any]:
    if db is not None:
        from ..models import ModelProviderConfigRecord, ModelProviderRecord
        from .provider_config import provider_view
        selected = db.scalar(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.scope_id == "local", ModelProviderConfigRecord.is_default.is_(True)))
        if selected:
            provider = db.get(ModelProviderRecord, selected.provider_id)
            if provider:
                view = provider_view(db, provider, selected)
                credential = None
                if selected.credential_id:
                    from .provider_config import credential_for
                    credential = credential_for(db, selected)
                configured = bool(credential or view["configured"])
                return {
                    "provider": provider.name,
                    "base_url": view["base_url"],
                    "model": view["default_model_id"],
                    "configured": configured,
                    "live_enabled": view["live_enabled"],
                    "key_hint": view["key_hint"],
                }
        configured_count = db.scalar(select(func.count()).select_from(ModelProviderConfigRecord).where(ModelProviderConfigRecord.scope_id == "local"))
        if configured_count:
            return {
                "provider": "未设置", "base_url": "", "model": "", "configured": False,
                "live_enabled": os.getenv("AGENTFLOW_ENABLE_LIVE_EXECUTION", "false").strip().lower() == "true",
                "key_hint": "未配置",
            }
    base_url = os.getenv("AGENTFLOW_LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    parts = urlsplit(base_url)
    safe_base_url = urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", "")).rstrip("/")
    return {
        "provider": os.getenv("AGENTFLOW_LLM_PROVIDER", "OpenRouter"),
        "base_url": safe_base_url,
        "model": os.getenv("AGENTFLOW_LLM_MODEL", "nvidia/nemotron-3.5-lightning:free"),
        "configured": bool(os.getenv("AGENTFLOW_LLM_API_KEY", "").strip()),
        "live_enabled": os.getenv("AGENTFLOW_ENABLE_LIVE_EXECUTION", "false").strip().lower() == "true",
        "key_hint": "已配置 ·••••" if os.getenv("AGENTFLOW_LLM_API_KEY", "").strip() else "未配置",
    }


def chat_completions_url(base_url: str) -> str:
    """Accept either an OpenAI-style API root or an already complete endpoint URL."""
    base_url = base_url.rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme not in {"https", "http"} or not parts.netloc:
        raise RuntimeError("模型 API 地址无效；请填写 HTTPS API 根地址或完整 chat/completions 地址。")
    if parts.path.rstrip("/").endswith("/chat/completions"):
        return base_url
    return urlunsplit((parts.scheme, parts.netloc, f"{parts.path.rstrip('/')}/chat/completions", parts.query, parts.fragment))


async def chat_completion(prompt: str, *, timeout_seconds: float = 60) -> dict[str, Any]:
    from ..db import SessionLocal
    from ..models import ModelProviderConfigRecord, ModelProviderRecord
    from .provider_config import credential_for, decrypt_secret
    try:
        with SessionLocal() as db:
            selected = db.scalar(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.scope_id == "local", ModelProviderConfigRecord.is_default.is_(True)))
            if selected:
                provider = db.get(ModelProviderRecord, selected.provider_id)
                credential = credential_for(db, selected)
                if provider and (credential or (provider.code == "openrouter" and os.getenv("AGENTFLOW_LLM_API_KEY", "").strip())):
                    api_key = decrypt_secret(credential) if credential else os.getenv("AGENTFLOW_LLM_API_KEY", "").strip()
                    if not api_key:
                        raise RuntimeError("未配置真实模型 API Key。请在供应商设置中配置凭据。")
                    from .provider_runtime import complete_provider
                    return await complete_provider(provider.code, provider.protocol, selected.api_base_url, api_key, selected.default_model_id, prompt)
            configured_count = db.scalar(select(func.count()).select_from(ModelProviderConfigRecord).where(ModelProviderConfigRecord.scope_id == "local"))
            if configured_count:
                raise RuntimeError("尚未选择默认模型供应商。请在模型供应商设置中保存默认配置。")
    except OperationalError as exc:
        if "no such table: model_provider_configs" not in str(exc).lower():
            raise
    api_key = os.getenv("AGENTFLOW_LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置真实模型 API Key。请在后端环境变量 AGENTFLOW_LLM_API_KEY 中设置。")
    settings = model_settings()
    base_url = os.getenv("AGENTFLOW_LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    endpoint = chat_completions_url(base_url)
    body = {
        "model": settings["model"],
        "messages": [{"role": "user", "content": prompt[:12000]}],
        "temperature": 0.2,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=10)) as client:
            logger.info("LLM request started provider=%s model=%s endpoint=%s", settings["provider"], settings["model"], settings["base_url"])
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("模型响应没有可用的文本内容。")
        usage = payload.get("usage") or {}
        tokens = usage.get("total_tokens")
        logger.info("LLM request completed provider=%s model=%s usage_reported=%s", settings["provider"], payload.get("model", settings["model"]), isinstance(tokens, int))
        return {"text": content[:20000], "model": payload.get("model", settings["model"]),
                "tokens": int(tokens) if isinstance(tokens, int) else None,
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}
    except httpx.TimeoutException as exc:
        logger.warning("LLM request timed out provider=%s model=%s", settings["provider"], settings["model"])
        raise RuntimeError(f"模型请求超时（{timeout_seconds:g} 秒）。") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("LLM request failed provider=%s model=%s status=%d", settings["provider"], settings["model"], status)
        # Do not include response body: provider errors may echo sensitive request data.
        raise RuntimeError(f"模型服务返回 HTTP {status}。请检查凭据、模型名称和服务商配置。") from exc
    except httpx.RequestError as exc:
        logger.warning("LLM request transport failed provider=%s model=%s error_type=%s", settings["provider"], settings["model"], type(exc).__name__)
        raise RuntimeError("无法连接模型服务，请检查后端网络与 API 地址。") from exc
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("LLM response processing failed provider=%s model=%s error_type=%s", settings["provider"], settings["model"], type(exc).__name__)
        raise RuntimeError("模型服务响应无法解析；请检查服务商响应格式。") from exc


async def test_connection() -> dict[str, Any]:
    result = await chat_completion("请只回复：连接成功", timeout_seconds=20)
    return {"ok": True, "model": result["model"], "tokens": result["tokens"]}
