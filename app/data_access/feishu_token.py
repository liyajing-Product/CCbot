"""Feishu user_access_token storage for office tools (calendar / tasks).

The app-level tenant_access_token (app identity) cannot read a user's private
calendar. Office tools therefore use a per-user OAuth ``user_access_token``,
obtained through the authorization-code flow and stored here keyed by the
user's Feishu ``open_id`` (which is also the channel binding key).

Tokens are stored locally in the same SQLite file as the rest of the profile
data. For a single-user local deployment this is acceptable; do not reuse this
table in a multi-tenant deployment without encrypting the token columns.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Float, String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, init_db
from app.data_access.session import SessionLocal


class FeishuUserToken(Base):
    __tablename__ = "feishu_user_tokens"

    open_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    access_token: Mapped[str] = mapped_column(String(1024), default="")
    refresh_token: Mapped[str] = mapped_column(String(1024), default="")
    # epoch seconds; 0 means unknown / already expired
    expires_at: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def save_token(
    *,
    open_id: str,
    user_id: str,
    access_token: str,
    refresh_token: str,
    expires_at: float,
) -> dict[str, Any]:
    init_db()
    oid = str(open_id or "").strip()
    uid = str(user_id or "").strip()
    if not oid or not uid or not access_token:
        raise ValueError("open_id, user_id and access_token are required")
    with SessionLocal() as session:
        row = session.get(FeishuUserToken, oid)
        if row is None:
            row = FeishuUserToken(open_id=oid, user_id=uid)
            session.add(row)
        row.user_id = uid
        row.access_token = access_token
        row.refresh_token = refresh_token or ""
        row.expires_at = float(expires_at or 0.0)
        session.commit()
        return {
            "open_id": row.open_id,
            "user_id": row.user_id,
            "access_token": row.access_token,
            "refresh_token": row.refresh_token,
            "expires_at": row.expires_at,
        }


def get_token(open_id: str) -> Optional[dict[str, Any]]:
    init_db()
    with SessionLocal() as session:
        row = session.get(FeishuUserToken, str(open_id or "").strip())
        if row is None:
            return None
        return {
            "open_id": row.open_id,
            "user_id": row.user_id,
            "access_token": row.access_token,
            "refresh_token": row.refresh_token,
            "expires_at": row.expires_at,
        }


def delete_token(open_id: str) -> bool:
    init_db()
    with SessionLocal() as session:
        row = session.get(FeishuUserToken, str(open_id or "").strip())
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True
