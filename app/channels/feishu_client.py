"""Feishu / Lark Open API client — tenant token, reply, interactive card.

Env (do not invent secrets; leave empty until user fills):
  FEISHU_APP_ID
  FEISHU_APP_SECRET
  FEISHU_VERIFICATION_TOKEN
  FEISHU_ENCRYPT_KEY
  FEISHU_API_BASE   default https://open.feishu.cn
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from base64 import b64decode
from typing import Any, Optional

import httpx

_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


def app_id() -> str:
    return (os.getenv("FEISHU_APP_ID") or "").strip()


def app_secret() -> str:
    return (os.getenv("FEISHU_APP_SECRET") or "").strip()


def verification_token() -> str:
    return (os.getenv("FEISHU_VERIFICATION_TOKEN") or "").strip()


def encrypt_key() -> str:
    return (os.getenv("FEISHU_ENCRYPT_KEY") or "").strip()


def api_base() -> str:
    return (os.getenv("FEISHU_API_BASE") or "https://open.feishu.cn").rstrip("/")


def is_configured() -> bool:
    return bool(app_id() and app_secret())


def verify_url_token(payload: dict[str, Any]) -> bool:
    """If FEISHU_VERIFICATION_TOKEN set, payload token must match."""
    expected = verification_token()
    if not expected:
        return True
    got = (
        payload.get("token")
        or (payload.get("header") or {}).get("token")
        or ""
    )
    return hmac.compare_digest(str(got), expected)


def verify_signature(
    *,
    timestamp: str,
    nonce: str,
    body: bytes | str,
    signature: str,
) -> bool:
    """x-lark-signature == SHA256(timestamp + nonce + encrypt_key + body)."""
    key = encrypt_key()
    if not key:
        return True  # optional in dev
    if not (timestamp and nonce and signature):
        return False
    body_str = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
    computed = hashlib.sha256(f"{timestamp}{nonce}{key}{body_str}".encode("utf-8")).hexdigest()
    try:
        return hmac.compare_digest(computed.encode(), signature.encode())
    except Exception:
        return False


def decrypt_encrypt_blob(encrypt_b64: str) -> dict[str, Any]:
    """Decrypt Feishu event Encrypt field (AES-256-CBC, key=SHA256(encrypt_key))."""
    key = encrypt_key()
    if not key:
        raise RuntimeError("FEISHU_ENCRYPT_KEY required to decrypt encrypted webhook")
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
    except ImportError as exc:
        raise RuntimeError("cryptography package required for Feishu encrypt payloads") from exc

    key_bytes = hashlib.sha256(key.encode("utf-8")).digest()
    raw = b64decode(encrypt_b64)
    iv, ciphertext = raw[:16], raw[16:]
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    return json.loads(plain.decode("utf-8"))


def maybe_unwrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """If body is {\"encrypt\": \"...\"}, decrypt to event JSON."""
    enc = payload.get("encrypt")
    if isinstance(enc, str) and enc and not payload.get("event") and not payload.get("type"):
        return decrypt_encrypt_blob(enc)
    return payload


def get_tenant_access_token(*, force: bool = False) -> str:
    if not is_configured():
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET not set")
    now = time.time()
    if not force and _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return str(_token_cache["token"])
    url = f"{api_base()}/open-apis/auth/v3/tenant_access_token/internal"
    with httpx.Client(timeout=20) as client:
        r = client.post(url, json={"app_id": app_id(), "app_secret": app_secret()})
        r.raise_for_status()
        data = r.json()
    code = data.get("code")
    if code is None:
        code = -1
    if int(code) != 0 or not data.get("tenant_access_token"):
        raise RuntimeError(f"tenant_access_token failed: code={data.get('code')} msg={data.get('msg')}")
    token = str(data["tenant_access_token"])
    expire = int(data.get("expire") or 7200)
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + max(expire - 300, 60)
    return token


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_tenant_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def send_text(
    *,
    receive_id: str,
    text: str,
    receive_id_type: str = "open_id",
) -> dict[str, Any]:
    """POST /open-apis/im/v1/messages"""
    if not is_configured():
        return {"ok": False, "skipped": True, "reason": "feishu_not_configured"}
    url = f"{api_base()}/open-apis/im/v1/messages"
    body = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    with httpx.Client(timeout=20) as client:
        r = client.post(
            url,
            params={"receive_id_type": receive_id_type},
            headers=_auth_headers(),
            json=body,
        )
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            return {"ok": False, "status_code": r.status_code, "data": data}
        return {"ok": int(data.get("code", -1)) == 0, "data": data}


def send_interactive_card(
    *,
    receive_id: str,
    card: dict[str, Any],
    receive_id_type: str = "open_id",
) -> dict[str, Any]:
    if not is_configured():
        return {"ok": False, "skipped": True, "reason": "feishu_not_configured"}
    url = f"{api_base()}/open-apis/im/v1/messages"
    # strip internal-only keys from card copy
    card_body = {k: v for k, v in card.items() if k not in ("thread_id", "preview_len")}
    body = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card_body, ensure_ascii=False),
    }
    with httpx.Client(timeout=20) as client:
        r = client.post(
            url,
            params={"receive_id_type": receive_id_type},
            headers=_auth_headers(),
            json=body,
        )
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            return {"ok": False, "status_code": r.status_code, "data": data}
        return {"ok": int(data.get("code", -1)) == 0, "data": data}


def reply_message(
    *,
    message_id: str,
    text: str = "",
    card: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Reply to an inbound message_id."""
    if not is_configured():
        return {"ok": False, "skipped": True, "reason": "feishu_not_configured"}
    if not message_id:
        return {"ok": False, "reason": "no_message_id"}
    url = f"{api_base()}/open-apis/im/v1/messages/{message_id}/reply"
    if card:
        card_body = {k: v for k, v in card.items() if k not in ("thread_id", "preview_len")}
        payload = {
            "msg_type": "interactive",
            "content": json.dumps(card_body, ensure_ascii=False),
        }
    else:
        payload = {
            "msg_type": "text",
            "content": json.dumps({"text": text or ""}, ensure_ascii=False),
        }
    with httpx.Client(timeout=20) as client:
        r = client.post(url, headers=_auth_headers(), json=payload)
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            return {"ok": False, "status_code": r.status_code, "data": data}
        return {"ok": int(data.get("code", -1)) == 0, "data": data}


def deliver_outbound(
    *,
    external_user_id: str,
    text: str,
    card: Optional[dict[str, Any]] = None,
    message_id: str = "",
) -> dict[str, Any]:
    """Prefer reply-to message; else DM by open_id; card if present."""
    if not is_configured():
        return {"ok": False, "skipped": True, "reason": "feishu_not_configured", "queued_locally": True}
    try:
        if message_id and card:
            return reply_message(message_id=message_id, card=card)
        if message_id and text:
            return reply_message(message_id=message_id, text=text)
        if card and external_user_id:
            return send_interactive_card(receive_id=external_user_id, card=card)
        if external_user_id and text:
            return send_text(receive_id=external_user_id, text=text)
    except Exception as exc:
        return {"ok": False, "reason": "feishu_deliver_error", "error": f"{type(exc).__name__}"}
    return {"ok": False, "reason": "no_target"}


def config_status() -> dict[str, Any]:
    return {
        "configured": is_configured(),
        "has_verification_token": bool(verification_token()),
        "has_encrypt_key": bool(encrypt_key()),
        "api_base": api_base(),
        "app_id_set": bool(app_id()),
    }


# ---------------------------------------------------------------------------
# OAuth user_access_token — office tools (calendar / tasks) read the user's
# private data, which the app-level tenant token cannot. The authorization
# code flow is wired in app.feishu_oauth; these helpers talk to Feishu.
# ---------------------------------------------------------------------------

def oauth_scope() -> str:
    return (
        os.getenv("FEISHU_OAUTH_SCOPE")
        or "calendar:calendar:readonly task:task:readonly contact:user.base:readonly"
    ).strip()


def oauth_authorize_url(*, state: str, redirect_uri: str) -> str:
    """Build the user-facing Feishu authorization URL."""
    from urllib.parse import urlencode

    return (
        f"{api_base()}/open-apis/authen/v1/authorize?"
        + urlencode({
            "app_id": app_id(),
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": oauth_scope(),
        })
    )


def _oauth_response(r: httpx.Response, data: dict[str, Any]) -> dict[str, Any]:
    if r.status_code >= 400 or int(data.get("code", -1)) != 0:
        return {"ok": False, "reason": "feishu_oauth_failed",
                "status_code": r.status_code, "data": data}
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    access = data.get("access_token") or inner.get("access_token") or ""
    refresh = data.get("refresh_token") or inner.get("refresh_token") or ""
    expires_in = int(data.get("expires_in") or inner.get("expires_in") or 7200)
    if not access:
        return {"ok": False, "reason": "feishu_oauth_no_access_token", "data": data}
    return {"ok": True, "access_token": access, "refresh_token": refresh,
            "expires_at": time.time() + max(expires_in, 60)}


def exchange_code(*, code: str, redirect_uri: str) -> dict[str, Any]:
    if not is_configured():
        return {"ok": False, "reason": "feishu_not_configured"}
    url = f"{api_base()}/open-apis/authen/v1/access_token"
    body = {
        "grant_type": "authorization_code",
        "client_id": app_id(),
        "client_secret": app_secret(),
        "code": code,
        "redirect_uri": redirect_uri,
    }
    try:
        with httpx.Client(timeout=20) as client:
            r = client.post(url, json=body)
        data = r.json() if r.content else {}
    except httpx.HTTPError as exc:
        return {"ok": False, "reason": "feishu_http_error", "error": type(exc).__name__}
    return _oauth_response(r, data)


def refresh_user_token(*, refresh_token: str) -> dict[str, Any]:
    if not is_configured():
        return {"ok": False, "reason": "feishu_not_configured"}
    if not refresh_token:
        return {"ok": False, "reason": "no_refresh_token"}
    url = f"{api_base()}/open-apis/authen/v1/refresh_access_token"
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": app_id(),
        "client_secret": app_secret(),
    }
    try:
        with httpx.Client(timeout=20) as client:
            r = client.post(url, json=body)
        data = r.json() if r.content else {}
    except httpx.HTTPError as exc:
        return {"ok": False, "reason": "feishu_http_error", "error": type(exc).__name__}
    out = _oauth_response(r, data)
    if out.get("ok") and not out.get("refresh_token"):
        out["refresh_token"] = refresh_token
    return out


def get_user_info(*, user_token: str) -> dict[str, Any]:
    url = f"{api_base()}/open-apis/authen/v1/user_info"
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {user_token}"})
        data = r.json() if r.content else {}
    except httpx.HTTPError as exc:
        return {"ok": False, "reason": "feishu_http_error", "error": type(exc).__name__}
    if r.status_code >= 400 or int(data.get("code", -1)) != 0:
        return {"ok": False, "reason": "feishu_user_info_failed",
                "status_code": r.status_code, "data": data}
    d = data.get("data") or {}
    return {"ok": True, "open_id": d.get("open_id") or "",
            "name": d.get("name") or "", "union_id": d.get("union_id") or ""}


def get_user_token(*, open_id: str) -> Optional[str]:
    """Return a valid user_access_token for an open_id, refreshing when needed."""
    from app.data_access.feishu_token import get_token as _get, save_token as _save

    rec = _get(open_id)
    if not rec or not rec.get("access_token"):
        return None
    if rec.get("expires_at", 0) > time.time() + 60:
        return rec["access_token"]
    if rec.get("refresh_token"):
        refreshed = refresh_user_token(refresh_token=rec["refresh_token"])
        if refreshed.get("ok") and refreshed.get("access_token"):
            _save(
                open_id=open_id,
                user_id=rec["user_id"],
                access_token=refreshed["access_token"],
                refresh_token=refreshed.get("refresh_token") or rec["refresh_token"],
                expires_at=refreshed.get("expires_at", 0),
            )
            return refreshed["access_token"]
    return rec["access_token"]


def _get_json(*, path: str, params: Optional[dict[str, Any]] = None,
               user_token: str = "") -> dict[str, Any]:
    url = f"{api_base()}{path}"
    headers = {"Authorization": f"Bearer {user_token}"} if user_token else _auth_headers()
    try:
        with httpx.Client(timeout=30) as client:
            r = client.get(url, params=params or {}, headers=headers)
        data = r.json() if r.content else {}
    except httpx.HTTPError as exc:
        return {"ok": False, "reason": "feishu_http_error", "error": type(exc).__name__}
    if r.status_code >= 400 or int(data.get("code", -1)) != 0:
        return {"ok": False, "reason": "feishu_api_error",
                "status_code": r.status_code, "data": data}
    return {"ok": True, "data": data.get("data") or data}


def list_calendars(*, user_token: str) -> dict[str, Any]:
    out = _get_json(path="/open-apis/calendar/v4/calendars",
                    params={"page_size": 50}, user_token=user_token)
    if not out.get("ok"):
        return out
    cals = (out.get("data") or {}).get("calendar_list") or []
    return {"ok": True, "calendars": [
        {"calendar_id": c.get("calendar_id") or "", "summary": c.get("summary") or "",
         "type": c.get("type") or ""}
        for c in cals if isinstance(c, dict)
    ]}


def list_calendar_events(*, user_token: str, calendar_id: str,
                         start_time: str = "", end_time: str = "") -> dict[str, Any]:
    params: dict[str, Any] = {"page_size": 50}
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    out = _get_json(path=f"/open-apis/calendar/v4/calendars/{calendar_id}/events",
                    params=params, user_token=user_token)
    if not out.get("ok"):
        return out
    events = []
    for e in (out.get("data") or {}).get("items") or []:
        if not isinstance(e, dict):
            continue
        st = e.get("start_time") or {}
        et = e.get("end_time") or {}
        events.append({
            "event_id": e.get("event_id") or "",
            "summary": e.get("summary") or "",
            "start": st.get("timestamp") or st.get("date") or "",
            "end": et.get("timestamp") or et.get("date") or "",
            "status": e.get("status") or "",
        })
    return {"ok": True, "events": events}


def list_tasks(*, user_token: str) -> dict[str, Any]:
    out = _get_json(path="/open-apis/task/v2/tasks",
                    params={"user_id_type": "open_id", "page_size": 50}, user_token=user_token)
    if not out.get("ok"):
        return out
    tasks = []
    for t in (out.get("data") or {}).get("items") or []:
        if not isinstance(t, dict):
            continue
        due = t.get("due")
        tasks.append({
            "guid": t.get("guid") or t.get("id") or "",
            "summary": t.get("summary") or "",
            "due": due.get("timestamp") if isinstance(due, dict) else "",
            "completed_at": t.get("completed_at") or "",
            "done": bool(t.get("completed_at")),
        })
    return {"ok": True, "tasks": tasks}
