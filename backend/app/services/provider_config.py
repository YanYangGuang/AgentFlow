"""Persistent local provider configuration and secret handling."""
import hashlib
import ipaddress
import os
import uuid
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ModelProviderConfigRecord, ModelProviderCredentialRecord, ModelProviderRecord, utcnow

LOCAL_SCOPE = "local"
PROVIDERS = (
    ("openai", "OpenAI", "https://api.openai.com/v1", "openai-compatible", 10),
    ("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "openai-compatible", 20),
    ("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "openai-compatible", 30),
    ("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta", "gemini", 40),
    ("anthropic", "Anthropic Claude", "https://api.anthropic.com/v1", "anthropic", 50),
    ("custom", "自定义兼容接口", "", "openai-compatible", 60),
)
PROVIDER_CODES = {name.casefold(): code for code, name, *_ in PROVIDERS}
PROVIDER_CODES.update({code: code for code, *_ in PROVIDERS})


def provider_code(value: str) -> str:
    return PROVIDER_CODES.get(value.strip().casefold(), value.strip().casefold())


def ensure_provider_catalog(db: Session) -> None:
    for code, name, base_url, protocol, sort_order in PROVIDERS:
        provider = db.scalar(select(ModelProviderRecord).where(ModelProviderRecord.code == code))
        if provider is None:
            db.add(ModelProviderRecord(id=f"provider_{code}", code=code, name=name, default_base_url=base_url,
                                       protocol=protocol, enabled=True, sort_order=sort_order))
        else:
            provider.name, provider.default_base_url, provider.protocol = name, base_url, protocol
            provider.enabled, provider.sort_order = True, sort_order
    db.commit()


def seed_legacy_default(db: Session) -> None:
    existing = db.scalar(select(ModelProviderConfigRecord).where(
        ModelProviderConfigRecord.scope_id == LOCAL_SCOPE,
        ModelProviderConfigRecord.is_default.is_(True),
    ))
    if existing:
        return
    code = provider_code(os.getenv("AGENTFLOW_LLM_PROVIDER", "OpenRouter"))
    provider = db.scalar(select(ModelProviderRecord).where(ModelProviderRecord.code == code))
    if provider is None:
        provider = db.get(ModelProviderRecord, "provider_openrouter")
    if provider is None:
        return
    existing_config = db.scalar(select(ModelProviderConfigRecord).where(
        ModelProviderConfigRecord.scope_id == LOCAL_SCOPE,
        ModelProviderConfigRecord.provider_id == provider.id,
    ))
    if existing_config:
        existing_config.is_default = True
        if existing_config.last_test_status == "unconfigured" and provider.code == "openrouter" and os.getenv("AGENTFLOW_LLM_API_KEY", "").strip():
            existing_config.last_test_status = "not_tested"
            existing_config.last_test_message = "供应商凭据已配置，请测试连接。"
        db.commit()
        return
    configured = bool(os.getenv("AGENTFLOW_LLM_API_KEY", "").strip()) if provider.code == "openrouter" else False
    db.add(ModelProviderConfigRecord(
        id=f"model_config_{uuid.uuid4().hex[:16]}", scope_id=LOCAL_SCOPE, provider_id=provider.id,
        api_base_url=os.getenv("AGENTFLOW_LLM_BASE_URL", provider.default_base_url).rstrip("/"),
        default_model_id=os.getenv("AGENTFLOW_LLM_MODEL", "nvidia/nemotron-3.5-lightning:free") if provider.code == "openrouter" else "",
        is_enabled=True, is_default=True, last_test_status="not_tested" if configured else "unconfigured",
        last_test_message="", config_version=1,
    ))
    db.commit()


def encryption_key() -> bytes:
    value = os.getenv("AGENTFLOW_CREDENTIAL_ENCRYPTION_KEY", "").strip().encode("ascii", errors="ignore")
    if not value:
        raise RuntimeError("尚未配置凭据加密密钥 AGENTFLOW_CREDENTIAL_ENCRYPTION_KEY。")
    try:
        Fernet(value)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("凭据加密密钥格式无效；请提供 Fernet URL-safe base64 密钥。") from exc
    return value


def encrypt_secret(secret: str) -> tuple[str, str]:
    encrypted = Fernet(encryption_key()).encrypt(secret.encode("utf-8")).decode("ascii")
    fingerprint = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]
    return encrypted, fingerprint


def decrypt_secret(record: ModelProviderCredentialRecord) -> str:
    try:
        return Fernet(encryption_key()).decrypt(record.encrypted_secret.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise RuntimeError("无法解密该供应商凭据；请检查当前凭据加密密钥。") from exc


def safe_base_url(value: str, protocol: str) -> str:
    raw = value.strip().rstrip("/")
    parts = urlsplit(raw)
    if protocol == "openai-compatible" and not raw:
        raise ValueError("请填写 API Base URL。")
    if raw and (parts.scheme not in {"https", "http"} or not parts.netloc or parts.username or parts.password):
        raise ValueError("API Base URL 格式无效；请使用不含凭据的 HTTP(S) 地址。")
    if raw:
        host = (parts.hostname or "").casefold().rstrip(".")
        if host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("API Base URL 不能指向本机、内网或云元数据地址。")
        try:
            address = ipaddress.ip_address(host)
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                raise ValueError("API Base URL 不能指向本机、内网或云元数据地址。")
        except ValueError as exc:
            if "不能指向" in str(exc):
                raise
        if parts.scheme != "https" and not os.getenv("AGENTFLOW_ALLOW_INSECURE_PROVIDER_URLS", "false").strip().lower() == "true":
            raise ValueError("供应商 API 地址必须使用 HTTPS。")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")) if raw else ""


def config_for(db: Session, code: str) -> ModelProviderConfigRecord | None:
    provider = db.scalar(select(ModelProviderRecord).where(ModelProviderRecord.code == provider_code(code)))
    if not provider:
        return None
    return db.scalar(select(ModelProviderConfigRecord).where(
        ModelProviderConfigRecord.scope_id == LOCAL_SCOPE,
        ModelProviderConfigRecord.provider_id == provider.id,
    ))


def credential_for(db: Session, config: ModelProviderConfigRecord) -> ModelProviderCredentialRecord | None:
    if not config.credential_id:
        return None
    credential = db.get(ModelProviderCredentialRecord, config.credential_id)
    if not credential or credential.scope_id != config.scope_id or credential.provider_id != config.provider_id:
        return None
    return credential


def provider_view(db: Session, provider: ModelProviderRecord, config: ModelProviderConfigRecord | None) -> dict:
    credential = credential_for(db, config) if config else None
    env_openrouter = provider.code == "openrouter" and bool(os.getenv("AGENTFLOW_LLM_API_KEY", "").strip())
    is_configured = bool(credential or env_openrouter)
    status = config.last_test_status if config else ("not_tested" if is_configured else "unconfigured")
    message = config.last_test_message if config else ""
    return {
        "code": provider.code,
        "name": provider.name,
        "default_base_url": provider.default_base_url,
        "protocol": provider.protocol,
        "enabled": provider.enabled,
        "configured": is_configured,
        "credential_saved": bool(credential),
        "base_url": config.api_base_url if config else (os.getenv("AGENTFLOW_LLM_BASE_URL", provider.default_base_url) if provider.code == "openrouter" else provider.default_base_url),
        "default_model_id": config.default_model_id if config else (os.getenv("AGENTFLOW_LLM_MODEL", "nvidia/nemotron-3.5-lightning:free") if provider.code == "openrouter" else ""),
        "key_hint": (f"已配置 ·••••{credential.key_fingerprint[-4:]}" if credential else ("已配置 ·••••" if env_openrouter else "未配置")),
        "last_test_status": status,
        "last_test_at": config.last_test_at if config else None,
        "last_test_message": message,
        "is_default": bool(config and getattr(config, "is_default", False)),
        "config_version": config.config_version if config else 0,
        "updated_at": config.updated_at if config else None,
        "live_enabled": os.getenv("AGENTFLOW_ENABLE_LIVE_EXECUTION", "false").strip().lower() == "true",
    }


def update_test_status(config: ModelProviderConfigRecord, status: str, message: str) -> None:
    config.last_test_status = status
    config.last_test_at = utcnow()
    config.last_test_message = message[:500]
