"""Offline medication reminder parsing and the confirmation-card proposal."""

from app.agent.schedules import medication, service
from app.data_access import user_scope


def test_detects_common_phrasings():
    yes = [
        "每天早上8点提醒我吃降压药",
        "早上8点和晚上8点提醒我吃阿司匹林，1片",
        "提醒我每天晚上9点服用二甲双胍 每次2粒",
    ]
    no = [
        "每天8点吃早饭",
        "提醒我明天8点开会",
        "今天天气不错",
        "帮我写封邮件",
    ]
    for text in yes:
        assert medication.looks_like_medication_reminder(text), text
    for text in no:
        assert not medication.looks_like_medication_reminder(text), text


def test_parse_times_and_dose():
    parsed = medication.parse_medication("早上8点和晚上8点提醒我吃阿司匹林，1片")
    assert parsed["name"] == "阿司匹林"
    assert parsed["dose"] == "1片"
    assert parsed["times"] == ["08:00", "20:00"]
    assert parsed["cron"] == "0 8,20 * * *"


def test_parse_rejects_incomplete():
    assert medication.parse_medication("提醒我吃药") is None
    assert medication.parse_medication("吃降压药") is None  # no time


def test_propose_then_decide_creates_medication_schedule(uid):
    with user_scope(uid):
        data = medication.propose_medication(uid, "每天早上8点提醒我吃降压药")
    proposal = data["schedule_proposal"]
    assert proposal["preview"]["job_kind"] == "medication"
    assert proposal["preview"]["kind_label"] == "用药提醒"
    assert proposal["preview"]["trigger"] == {"type": "cron", "expr": "0 8 * * *"}

    with user_scope(uid):
        result = service.decide(uid, proposal["id"], True)
    assert result["status"] == "confirmed"
    assert result["schedule"]["name"] == "降压药"
    assert result["schedule"]["job_kind"] == "medication"


def test_medication_requires_cron(uid):
    with user_scope(uid):
        try:
            service.validate(uid, {
                "name": "降压药",
                "job_kind": "medication",
                "trigger": {"type": "once", "run_at": "2030-01-01T08:00:00"},
                "prompt_text": "该吃降压药了",
            })
        except ValueError as exc:
            assert "用药提醒" in str(exc)
        else:
            raise AssertionError("once trigger must be rejected for medication")
