"""Feishu OAuth authorization endpoints for office tools.

``GET /api/feishu/oauth/start`` builds the Feishu authorization URL; the ``state``
is a signed user token (``app.auth``), so the callback recovers the user_id
without any server-side state table.

``GET /api/feishu/oauth/callback`` exchanges the code for a user_access_token,
stores it, and binds the Feishu ``open_id`` to the browser session's user_id.
"""

from __future__ import annotations

import os
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth import mint_user_token, require_user, verify_user_token
from app.channels import feishu_client
from app.channels.binding import bind_channel
from app.data_access.feishu_token import save_token

router = APIRouter(prefix="/api/feishu/oauth", tags=["feishu_oauth"])


def oauth_redirect_uri() -> str:
    explicit = (os.getenv("FEISHU_OAUTH_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    public = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if public:
        return f"{public}/api/feishu/oauth/callback"
    return "http://127.0.0.1:8787/api/feishu/oauth/callback"


def _page(title: str, body: str, ok: bool = True) -> str:
    color = "#16A34A" if ok else "#F53F3F"
    return (
        '<!doctype html><html lang="zh"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title>"
        '<body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#F7F7F8;'
        'display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0">'
        '<div style="background:#fff;border:1px solid #E7E7EA;border-radius:16px;padding:32px;max-width:420px">'
        f'<h1 style="font-size:18px;margin:0 0 8px;color:{color}">{escape(title)}</h1>'
        f'<p style="color:#5F5F66;margin:0;line-height:1.6">{escape(body)}</p></div></body></html>'
    )


@router.get("/start")
async def oauth_start(request: Request):
    user_id = require_user(request)
    if not feishu_client.is_configured():
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "code": "feishu_not_configured",
                "message": "飞书应用未配置（FEISHU_APP_ID / FEISHU_APP_SECRET）。",
            },
        )
    state = mint_user_token(user_id, ttl_seconds=600)
    url = feishu_client.oauth_authorize_url(state=state, redirect_uri=oauth_redirect_uri())
    return {"ok": True, "authorize_url": url}


@router.get("/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return HTMLResponse(_page("授权未完成", f"飞书返回错误：{error}", ok=False), status_code=400)
    user_id = verify_user_token(state)
    if not user_id:
        return HTMLResponse(_page("授权链接无效或已过期", "请回到对话页重新发起授权。", ok=False), status_code=400)
    if not code:
        return HTMLResponse(_page("缺少授权码", "请重新发起授权。", ok=False), status_code=400)

    exchanged = feishu_client.exchange_code(code=code, redirect_uri=oauth_redirect_uri())
    if not exchanged.get("ok"):
        return HTMLResponse(
            _page("授权失败", f"无法换取访问令牌：{exchanged.get('reason')}", ok=False), status_code=400)

    access = exchanged["access_token"]
    info = feishu_client.get_user_info(user_token=access)
    if not info.get("ok") or not info.get("open_id"):
        return HTMLResponse(_page("授权失败", "无法获取飞书用户信息。", ok=False), status_code=400)

    open_id = info["open_id"]
    try:
        bind_channel("feishu", open_id, user_id, display_name=info.get("name") or "")
    except ValueError as exc:
        return HTMLResponse(_page("绑定失败", str(exc), ok=False), status_code=400)

    save_token(
        open_id=open_id,
        user_id=user_id,
        access_token=access,
        refresh_token=exchanged.get("refresh_token") or "",
        expires_at=exchanged.get("expires_at", 0),
    )
    name = info.get("name") or open_id
    return HTMLResponse(_page("授权成功", f"已绑定飞书账号：{name}。现在回到对话问「我今天有什么日程」试试。"))
