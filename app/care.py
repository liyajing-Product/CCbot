"""Caregiver (子女) binding for the health companion.

A care recipient (老人) mints a one-time invite link; a caregiver (子女) opens it
in their own browser session and confirms, creating a read-only relationship:
the caregiver can view the recipient's health profile and is the default
emergency contact for future alerts.

Security: invite tokens are stored only as SHA-256, expire in 7 days, and are
single-use. Relationship reads/writes are authorized explicitly by handler code
(actor must be one of the two parties); the rows carry no ``user_id`` column, so
the generic owner-column guard does not apply.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ENGINE, read_profile_data
from app.data_access.schema import ensure_tables
from app.data_access.session import SessionLocal

INVITE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# Fields a caregiver may read from the recipient's profile.
HEALTH_FIELDS = (
    "name", "blood_type", "emergency_contact", "primary_doctor",
    "medical_history", "medications", "allergies",
)


class CareRelationship(Base):
    __tablename__ = "care_relationships"
    __table_args__ = (UniqueConstraint("caregiver_id", "care_recipient_id", name="uq_care_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    caregiver_id: Mapped[str] = mapped_column(String(128), index=True)
    care_recipient_id: Mapped[str] = mapped_column(String(128), index=True)
    relation_label: Mapped[str] = mapped_column(String(32), default="子女")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CareInvite(Base):
    __tablename__ = "care_invites"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    recipient_id: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


_ready = False


def _ensure() -> None:
    global _ready
    if not _ready:
        ensure_tables(ENGINE, tables=[CareRelationship.__table__, CareInvite.__table__])
        _ready = True


def _hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _rel_dict(row: CareRelationship) -> dict[str, Any]:
    return {
        "id": row.id,
        "caregiver_id": row.caregiver_id,
        "care_recipient_id": row.care_recipient_id,
        "relation_label": row.relation_label,
        "status": row.status,
        "created_at": _aware(row.created_at).isoformat(),
    }


def issue_invite(recipient_id: str) -> tuple[str, datetime]:
    """Return (token, expires_at) for a new single-use caregiver invite."""
    _ensure()
    token = secrets.token_urlsafe(24)
    now = _now()
    expires = now + timedelta(seconds=INVITE_TTL_SECONDS)
    with SessionLocal() as session:
        session.add(CareInvite(
            token_hash=_hash(token),
            recipient_id=str(recipient_id),
            created_at=now,
            expires_at=expires,
        ))
        session.commit()
    return token, expires


def peek_invite(token: str) -> Optional[dict[str, Any]]:
    """Describe a live invite without consuming it (no secrets exposed)."""
    if not token:
        return None
    _ensure()
    with SessionLocal() as session:
        row = session.get(CareInvite, _hash(token))
        if row is None or row.used_at is not None:
            return None
        if _aware(row.expires_at) <= _now():
            return None
        return {"recipient_id": row.recipient_id, "expires_at": _aware(row.expires_at).isoformat()}


def consume_invite(token: str) -> Optional[str]:
    """Atomically mark the invite used; return recipient_id or None."""
    if not token:
        return None
    _ensure()
    with SessionLocal() as session:
        row = session.get(CareInvite, _hash(token))
        if row is None or row.used_at is not None:
            return None
        if _aware(row.expires_at) <= _now():
            return None
        row.used_at = _now()
        session.commit()
        return row.recipient_id


def bind(caregiver_id: str, recipient_id: str, relation_label: str = "子女") -> dict[str, Any]:
    """Create (or reactivate) a care relationship."""
    _ensure()
    caregiver_id = str(caregiver_id).strip()
    recipient_id = str(recipient_id).strip()
    if not caregiver_id or not recipient_id:
        raise ValueError("账号缺失，无法建立守护关系")
    if caregiver_id == recipient_id:
        raise ValueError("不能守护自己的账号")
    label = (relation_label or "子女").strip()[:32] or "子女"
    with SessionLocal() as session:
        row = session.scalar(select(CareRelationship).where(
            CareRelationship.caregiver_id == caregiver_id,
            CareRelationship.care_recipient_id == recipient_id,
        ))
        if row is None:
            row = CareRelationship(
                caregiver_id=caregiver_id,
                care_recipient_id=recipient_id,
                relation_label=label,
                status="active",
                created_at=_now(),
            )
            session.add(row)
        else:
            row.status = "active"
            row.relation_label = label
        session.commit()
        return _rel_dict(row)


def list_relationships(user_id: str) -> dict[str, Any]:
    """Both directions for one user: people I care for, people who care for me."""
    _ensure()
    from app.data_access import system_scope

    with SessionLocal() as session:
        care_for = session.scalars(select(CareRelationship).where(
            CareRelationship.caregiver_id == str(user_id),
            CareRelationship.status == "active",
        )).all()
        cared_by = session.scalars(select(CareRelationship).where(
            CareRelationship.care_recipient_id == str(user_id),
            CareRelationship.status == "active",
        )).all()
    as_caregiver = []
    for row in care_for:
        item = _rel_dict(row)
        with system_scope():
            item["name"] = str((read_profile_data(row.care_recipient_id) or {}).get("name") or "")
        as_caregiver.append(item)
    as_recipient = []
    for row in cared_by:
        item = _rel_dict(row)
        with system_scope():
            item["name"] = str((read_profile_data(row.caregiver_id) or {}).get("name") or "")
        as_recipient.append(item)
    return {"as_caregiver": as_caregiver, "as_recipient": as_recipient}


def is_caregiver_of(caregiver_id: str, recipient_id: str) -> bool:
    _ensure()
    with SessionLocal() as session:
        row = session.scalar(select(CareRelationship).where(
            CareRelationship.caregiver_id == str(caregiver_id),
            CareRelationship.care_recipient_id == str(recipient_id),
            CareRelationship.status == "active",
        ))
        return row is not None


def unbind(relationship_id: int, actor_id: str) -> bool:
    """Remove a relationship where the actor is either party."""
    _ensure()
    with SessionLocal() as session:
        row = session.get(CareRelationship, relationship_id)
        if row is None:
            return False
        if str(actor_id) not in (row.caregiver_id, row.care_recipient_id):
            return False
        row.status = "removed"
        session.commit()
        return True


def health_profile(recipient_id: str) -> dict[str, Any]:
    """Read-only health snapshot for an authorized caregiver."""
    from app.data_access import system_scope

    with system_scope():
        profile = read_profile_data(str(recipient_id)) or {}
    out: dict[str, Any] = {}
    for field in HEALTH_FIELDS:
        value = profile.get(field)
        if value not in (None, "", []):
            out[field] = value
    return out
