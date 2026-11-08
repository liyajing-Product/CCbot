"""Feishu office tools: registration, contract, token store and degradation."""

from __future__ import annotations

import time

from app.agent import tool_registry
from app.channels import feishu_client
from app.tools import feishu_office


def test_office_tools_registered():
    names = {t["name"] for t in tool_registry.list_tools()}
    assert {"feishu_calendar_list", "feishu_calendar_events", "feishu_task_list"} <= names
    for name in ("feishu_calendar_list", "feishu_calendar_events", "feishu_task_list"):
        spec = tool_registry.get(name)
        assert spec is not None
        assert spec.risk_level == "read"
        assert spec.requires_confirm is False


def test_calendar_list_not_configured(uid, monkeypatch):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    out = feishu_office.feishu_calendar_list(user_id=uid)
    assert out["ok"] is False
    assert out["reason"] == "feishu_not_configured"


def test_calendar_list_not_authorized(uid, monkeypatch):
    monkeypatch.setattr(feishu_client, "is_configured", lambda: True)
    monkeypatch.setattr(feishu_office, "list_bindings", lambda user_id: [])
    out = feishu_office.feishu_calendar_list(user_id=uid)
    assert out["ok"] is False
    assert out["reason"] == "feishu_not_authorized"


def test_task_list_passes_user_token(uid, monkeypatch):
    seen = {}
    monkeypatch.setattr(feishu_client, "is_configured", lambda: True)
    monkeypatch.setattr(feishu_office, "_user_token_for", lambda u: ("ou_1", "tok_1"))

    def fake_list_tasks(*, user_token):
        seen["token"] = user_token
        return {"ok": True, "tasks": []}

    monkeypatch.setattr(feishu_client, "list_tasks", fake_list_tasks)
    out = feishu_office.feishu_task_list(user_id=uid)
    assert out == {"ok": True, "tasks": []}
    assert seen["token"] == "tok_1"


def test_calendar_events_requires_calendar_id(uid, monkeypatch):
    monkeypatch.setattr(feishu_client, "is_configured", lambda: True)
    monkeypatch.setattr(feishu_office, "_user_token_for", lambda u: ("ou_1", "tok_1"))
    out = feishu_office.feishu_calendar_events(calendar_id="", user_id=uid)
    assert out["ok"] is False
    assert out["reason"] == "missing_calendar_id"


def test_token_store_roundtrip(data_dir):
    from app.data_access.feishu_token import delete_token, get_token, save_token

    save_token(open_id="ou_1", user_id="u-1", access_token="a", refresh_token="r",
               expires_at=time.time() + 3600)
    rec = get_token("ou_1")
    assert rec is not None
    assert rec["access_token"] == "a"
    assert rec["refresh_token"] == "r"
    assert rec["user_id"] == "u-1"
    assert delete_token("ou_1") is True
    assert get_token("ou_1") is None


def test_oauth_start_requires_feishu_config(client, auth, monkeypatch):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    r = client.get("/api/feishu/oauth/start", headers=auth("u-x"))
    assert r.status_code == 503
    assert r.json()["code"] == "feishu_not_configured"


def test_oauth_start_builds_authorize_url(client, auth, monkeypatch):
    monkeypatch.setattr(feishu_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        feishu_client,
        "oauth_authorize_url",
        lambda *, state, redirect_uri: f"https://open.feishu.cn/auth?state={state}&redirect={redirect_uri}",
    )
    r = client.get("/api/feishu/oauth/start", headers=auth("u-x"))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["authorize_url"].startswith("https://open.feishu.cn/auth?state=")


def test_oauth_callback_rejects_bad_state(client, auth, monkeypatch):
    r = client.get("/api/feishu/oauth/callback", params={"code": "c", "state": "bad"})
    assert r.status_code == 400
    assert "无效" in r.text or "授权" in r.text


def test_oauth_callback_exempt_from_session(monkeypatch):
    # Feishu redirects here without a browser session cookie; the signed state
    # is the credential. The session wall must not 401 this path.
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    from app.main import app
    from tests.conftest import RawTestClient

    raw = RawTestClient(app)
    r = raw.get("/api/feishu/oauth/callback", params={"code": "c", "state": "bad"})
    assert r.status_code == 400
