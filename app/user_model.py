"""Per-user "bring your own key" (BYOK) model configuration.

A user may supply their own OpenAI-compatible endpoint (base_url + model +
api_key). The key is Fernet-encrypted with ``SECRETS_FERNET_KEY`` and is never
returned by any API; only a masked preview leaves this module. When set, the
user's spec is tried before every operator-configured model for that request.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ENGINE
from app.data_access.schema import ensure_tables
from app.data_access.session import SessionLocal
from app.gateway.config import ModelSpec

# Vendor presets shown in the UI; base_url/model are editable by the user.
VENDORS = {
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "kimi": {"label": "Kimi (Moonshot)", "base_url": "https://api.moonshot.cn/v1", "model": "kimi-k2.6"},
    "qwen": {"label": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "custom": {"label": "自定义", "base_url": "", "model": ""},
}

# Current request's resolved user spec (set by the identity middleware).
_current_spec: ContextVar[Optional[ModelSpec]] = ContextVar("user_llm_spec", default=None)


class UserModelConfig(Base):
    __tablename__ = "user_model_configs"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(512), default="")
    model: Mapped[str] = mapped_column(String(256), default="")
    vendor: Mapped[str] = mapped_column(String(64), default="custom")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


_ready = False


def _ensure() -> None:
    global _ready
    if not _ready:
        ensure_tables(ENGINE, tables=[UserModelConfig.__table__])
        _ready = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fernet():
    from cryptography.fernet import Fernet, MultiFernet

    raw = (os.getenv("SECRETS_FERNET_KEY") or "").strip()
    if not raw:
        raise RuntimeError("SECRETS_FERNET_KEY not set")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    try:
        return MultiFernet([Fernet(k.encode("ascii")) for k in keys])
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("SECRETS_FERNET_KEY invalid") from exc


def vault_configured() -> bool:
    try:
        _fernet()
        return True
    except RuntimeError:
        return False


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


class ModelConnectionError(ValueError):
    """Safe, actionable validation failure; never includes upstream payloads or keys."""


def validate_connection(spec: ModelSpec) -> None:
    from app.gateway import providers

    try:
        completion = providers.call(
            spec, api_key=spec.api_key(), system="This is a connection test.",
            user="Reply OK.", tier="fast", timeout=12.0,
            temperature=None, max_tokens=32,
        )
    except providers.ProviderError as exc:
        if exc.kind == "auth":
            message = "API Key 无效或没有访问权限，请检查密钥和模型授权"
        elif exc.status == 404 or "no_api" in str(exc):
            message = "接口或模型不存在，请检查 Base URL 和模型名称"
        elif exc.kind == "rate_limited":
            message = "接口额度不足或请求受限，请检查余额与调用限制后重试"
        elif exc.kind == "timeout":
            message = "模型连接超时，请检查接口地址或稍后重试"
        elif exc.kind == "connect":
            message = "无法连接模型服务，请检查接口地址和服务器网络"
        elif exc.kind == "bad_request":
            message = "接口拒绝请求，请检查模型名称和接口兼容性"
        else:
            message = "模型服务暂时异常，请稍后重试"
        raise ModelConnectionError(message) from None
    except (ValueError, TypeError, AttributeError):
        raise ModelConnectionError("接口响应格式不兼容，请使用 OpenAI 兼容接口") from None
    # A reasoning model can consume the small probe budget before producing text.
    # A normal length stop still proves that the endpoint accepted the credentials/model.
    if not completion.content and completion.finish_reason != "length":
        raise ModelConnectionError("模型未返回有效内容，请检查接口兼容性或更换模型")


def save_config(user_id: str, base_url: str, model: str, api_key: str, vendor: str = "custom", *, verify: bool = False) -> dict[str, Any]:
    """Upsert the user's model config; api_key is encrypted, never returned."""
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("缺少账号")
    base_url = (base_url or "").strip().rstrip("/")
    model = (model or "").strip()
    api_key = (api_key or "").strip()
    vendor = (vendor or "custom").strip()[:64]
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise ValueError("Base URL 需要以 http:// 或 https:// 开头")
    parsed = urlsplit(base_url)
    if not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Base URL 格式不正确，请填写不含账号、参数或片段的基础地址")
    if parsed.path.rstrip("/").endswith("/chat/completions"):
        raise ValueError("Base URL 请只填写基础地址，不要包含 /chat/completions")
    if not model:
        raise ValueError("需要填写模型名称")
    if not api_key:
        raise ValueError("需要填写 API Key")
    encrypted = _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")
    if verify:
        validate_connection(ModelSpec(
            id="user_byok_probe", model=model, base_url=base_url,
            vendor=vendor, _literal_api_key=api_key,
        ))
    _ensure()
    now = _now()
    with SessionLocal() as session:
        row = session.get(UserModelConfig, uid)
        if row is None:
            row = UserModelConfig(user_id=uid, created_at=now)
            session.add(row)
        row.api_key_encrypted = encrypted
        row.base_url = base_url
        row.model = model
        row.vendor = vendor
        row.updated_at = now
        session.commit()
    return public_status(uid)


def get_config(user_id: str) -> Optional[dict[str, Any]]:
    """Decrypt and return {base_url, model, api_key, vendor} or None."""
    _ensure()
    with SessionLocal() as session:
        row = session.get(UserModelConfig, str(user_id))
    if row is None or not row.api_key_encrypted:
        return None
    try:
        api_key = _fernet().decrypt(row.api_key_encrypted.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
    return {"base_url": row.base_url, "model": row.model, "api_key": api_key, "vendor": row.vendor}


def delete_config(user_id: str) -> None:
    _ensure()
    with SessionLocal() as session:
        row = session.get(UserModelConfig, str(user_id))
        if row is not None:
            session.delete(row)
            session.commit()


def public_status(user_id: str) -> dict[str, Any]:
    """Safe status for the API: has_key + masked preview, never the raw key."""
    cfg = get_config(str(user_id))
    if not cfg:
        return {"configured": False, "has_key": False, "vendor": "", "base_url": "", "model": "", "masked_key": ""}
    return {
        "configured": True,
        "has_key": bool(cfg.get("api_key")),
        "vendor": cfg.get("vendor") or "custom",
        "base_url": cfg.get("base_url") or "",
        "model": cfg.get("model") or "",
        "masked_key": _mask_key(cfg.get("api_key") or ""),
    }


def build_spec(user_id: str) -> Optional[ModelSpec]:
    """Build the request-time spec for this user, or None when no key is set."""
    cfg = get_config(str(user_id))
    if not cfg or not cfg.get("api_key") or not cfg.get("base_url") or not cfg.get("model"):
        return None
    return ModelSpec(
        id="user_byok",
        model=cfg["model"],
        base_url=cfg["base_url"],
        vendor=cfg.get("vendor") or "custom",
        _literal_api_key=cfg["api_key"],
    )


# --- per-request context (set by the identity middleware) ---


def set_current(spec: Optional[ModelSpec]) -> None:
    _current_spec.set(spec)


def get_current() -> Optional[ModelSpec]:
    return _current_spec.get()


def clear_current() -> None:
    _current_spec.set(None)
