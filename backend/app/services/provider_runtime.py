"""Small provider protocol adapters for connection checks and model discovery."""
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from .live_model import chat_completions_url


def _endpoint(base_url: str, suffix: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/chat/completions"):
        root = root[: -len("/chat/completions")]
    return f"{root}/{suffix.lstrip('/')}"


def _validate_target(base_url: str) -> None:
    host = urlsplit(base_url).hostname or ""
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise RuntimeError("无法解析供应商 API 地址。") from exc
    if not addresses:
        raise RuntimeError("供应商 API 地址没有可用的网络地址。")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise RuntimeError("供应商 API 地址解析到了内网或保留网络，已阻止请求。")


def _headers(protocol: str, api_key: str) -> dict[str, str]:
    if protocol == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    if protocol == "gemini":
        return {"x-goog-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _models_url(code: str, protocol: str, base_url: str, api_key: str) -> tuple[str, dict[str, str]]:
    headers = _headers(protocol, api_key)
    if protocol == "anthropic":
        return _endpoint(base_url, "models?limit=100"), headers
    if protocol == "gemini":
        return _endpoint(base_url, "models"), headers
    return _endpoint(base_url, "models"), headers


def _safe_provider_error(exc: Exception) -> RuntimeError:
    if isinstance(exc, httpx.TimeoutException):
        return RuntimeError("供应商请求超时。")
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        messages = {401: "凭据无效或已撤销（HTTP 401）。", 403: "凭据无权访问该接口（HTTP 403）。",
                    429: "供应商请求限流（HTTP 429）。"}
        return RuntimeError(messages.get(status, f"供应商接口返回 HTTP {status}。"))
    if isinstance(exc, httpx.RequestError):
        return RuntimeError("无法连接供应商；请检查网络及 API 地址。")
    return RuntimeError("供应商响应格式无效。")


def _normalize_models(code: str, protocol: str, payload: dict) -> list[dict]:
    raw = payload.get("data", []) if protocol in {"anthropic", "openai-compatible"} else payload.get("models", [])
    output = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name")
        if not isinstance(model_id, str) or not model_id:
            continue
        if protocol == "gemini" and not item.get("supportedGenerationMethods"):
            continue
        output.append({"id": model_id.removeprefix("models/"), "name": item.get("display_name") or item.get("displayName") or model_id,
                       "context_length": item.get("context_length") or item.get("contextLength"), "source": "provider"})
    return output


async def fetch_models(code: str, protocol: str, base_url: str, api_key: str) -> list[dict]:
    _validate_target(base_url)
    url, headers = _models_url(code, protocol, base_url, api_key)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8)) as client:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
        return _normalize_models(code, protocol, response.json())
    except Exception as exc:
        raise _safe_provider_error(exc) from exc


async def verify_provider(code: str, protocol: str, base_url: str, api_key: str, model_id: str = "") -> dict:
    models = await fetch_models(code, protocol, base_url, api_key)
    return {"ok": True, "status": "connected", "message": "供应商模型接口访问成功。", "models_available": len(models)}


async def complete_provider(code: str, protocol: str, base_url: str, api_key: str, model: str, prompt: str) -> dict:
    try:
        _validate_target(base_url)
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as client:
            if protocol == "anthropic":
                response = await client.post(_endpoint(base_url, "messages"), headers={**_headers(protocol, api_key), "content-type": "application/json"},
                    json={"model": model, "max_tokens": 2048, "messages": [{"role": "user", "content": prompt[:12000]}]})
                response.raise_for_status(); payload = response.json()
                text = "".join(item.get("text", "") for item in payload.get("content", []) if item.get("type") == "text")
                usage = payload.get("usage", {})
                tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
            elif protocol == "gemini":
                response = await client.post(_endpoint(base_url, f"models/{model}:generateContent"), headers=_headers(protocol, api_key),
                    json={"contents": [{"parts": [{"text": prompt[:12000]}]}]})
                response.raise_for_status(); payload = response.json()
                text = "".join(part.get("text", "") for part in (payload.get("candidates") or [{}])[0].get("content", {}).get("parts", []))
                tokens = payload.get("usageMetadata", {}).get("totalTokenCount")
            else:
                response = await client.post(chat_completions_url(base_url), headers={**_headers(protocol, api_key), "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt[:12000]}], "temperature": 0.2})
                response.raise_for_status(); payload = response.json()
                text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "")
                tokens = (payload.get("usage") or {}).get("total_tokens")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("模型响应没有可用的文本内容。")
        return {"text": text[:20000], "model": model, "tokens": tokens if isinstance(tokens, int) else None}
    except RuntimeError:
        raise
    except Exception as exc:
        raise _safe_provider_error(exc) from exc
