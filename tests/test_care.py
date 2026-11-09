"""Caregiver (子女) binding for the health companion.

Covers the invite lifecycle, authorization, health-profile scoping and unbind.
"""

import pytest

from app import care, db
from app.data_access import user_scope


@pytest.fixture
def elder():
    with user_scope("u-elder"):
        yield "u-elder"


@pytest.fixture
def child():
    with user_scope("u-child"):
        yield "u-child"


def test_invite_lifecycle_single_use(elder):
    token, _ = care.issue_invite(elder)
    assert care.peek_invite(token)["recipient_id"] == elder
    assert care.consume_invite(token) == elder
    assert care.peek_invite(token) is None
    assert care.consume_invite(token) is None


def test_bind_and_authorize(elder, child):
    rel = care.bind(child, elder, "女儿")
    assert rel["caregiver_id"] == child
    assert rel["care_recipient_id"] == elder
    assert care.is_caregiver_of(child, elder)
    assert not care.is_caregiver_of(elder, child)

    rels = care.list_relationships(child)
    assert [r["care_recipient_id"] for r in rels["as_caregiver"]] == [elder]
    rels = care.list_relationships(elder)
    assert [r["caregiver_id"] for r in rels["as_recipient"]] == [child]

    assert care.unbind(rel["id"], child)
    assert not care.is_caregiver_of(child, elder)


def test_self_bind_rejected(elder):
    with pytest.raises(ValueError):
        care.bind(elder, elder)


def test_health_profile_scoped_to_health_fields(elder):
    with user_scope(elder):
        db.merge_and_save(elder, {
            "name": "张桂芳",
            "city": "上海",  # not a health field → must not leak
            "medical_history": ["高血压"],
            "medications": ["阿司匹林"],
            "allergies": ["青霉素"],
            "blood_type": "A 型",
        })
    health = care.health_profile(elder)
    assert health["name"] == "张桂芳"
    assert health["medical_history"] == ["高血压"]
    assert health["medications"] == ["阿司匹林"]
    assert "city" not in health
    assert "interests" not in health


def test_unbind_requires_party(elder, child):
    rel = care.bind(child, elder)
    assert not care.unbind(rel["id"], "u-stranger")
    assert care.is_caregiver_of(child, elder)
    assert care.unbind(rel["id"], elder)
    assert not care.is_caregiver_of(child, elder)
