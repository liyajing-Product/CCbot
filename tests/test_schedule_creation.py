"""Regression: usable creation without a model, including legacy bad profile timezones."""
from datetime import datetime, timedelta, timezone
import pytest
from app import db
from app.auth import mint_user_token
from app.agent.schedules import service, runner, medication
from app.main import app
from tests.conftest import RawTestClient


def sample(**updates):
    return {'name': '合成用药提醒', 'job_kind': 'medication',
            'trigger': {'type': 'cron', 'expr': '15 8 * * *'},
            'prompt_text': '合成提醒内容', 'delivery': 'in_app', **updates}


@pytest.mark.parametrize('text,clock', [
    ('每天早上八点提醒我吃降压药', '08:00'),
    ('每天晚上八点半提醒我吃降压药', '20:30'),
    ('每天上午八点十五分提醒我吃降压药', '08:15'),
    ('每天08:45提醒我吃降压药', '08:45'),
])
def test_chinese_and_colon_clock(text, clock):
    assert medication.looks_like_medication_reminder(text)
    parsed = medication.parse_medication(text)
    assert parsed['times'] == [clock]
    minute, hour = map(int, [clock[3:], clock[:2]])
    assert parsed['cron'] == f'{minute} {hour} * * *'


def test_never_approximates_mixed_minutes_or_ignores_invalid_times():
    assert medication.parse_medication('每天早上8点和晚上9点半提醒我吃降压药') is None
    assert medication.parse_medication('每天早上8点和晚上25点提醒我吃降压药') is None


def test_invalid_profile_timezone_uses_visible_valid_default(uid):
    db.save_profile(uid, {'tz': 'shanxi'})
    assert service.default_timezone(uid) == 'Asia/Shanghai'
    assert service.validate(uid, sample())['tz'] == 'Asia/Shanghai'
    assert db.get_profile(uid)['tz'] == 'shanxi'  # Do not rewrite the user's profile.
    with pytest.raises(ValueError, match='时区无效'):
        service.validate(uid, sample(tz='not-a-zone'))


def test_date_specific_medication_is_not_silently_daily(uid):
    result = medication.propose_medication(uid, '明天早上八点提醒我吃降压药')
    assert 'schedule_proposal' not in result
    assert '一次性' in result['messages'][0]['content']


def test_panel_creation_is_confirmed_owned_and_executable(uid, monkeypatch):
    client = RawTestClient(app)
    headers = {'X-User-Token': mint_user_token(uid)}
    db.save_profile(uid, {'tz': 'shanxi'})
    listing = client.get('/api/schedules', headers=headers)
    assert listing.status_code == 200
    assert listing.json()['data']['tz'] == 'Asia/Shanghai'
    assert listing.json()['data']['scheduler']['enabled'] is False
    response = client.post('/api/schedules/proposals', headers=headers, json=sample())
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['needs_confirm'] is True
    assert service.list_schedules(uid) == []
    proposal_id = data['proposal']['id']
    other = {'X-User-Token': mint_user_token('synthetic-other-owner')}
    assert client.post(f'/api/schedules/proposals/{proposal_id}/decide', headers=other,
                       json={'confirmed': True}).status_code == 404
    saved = client.post(f'/api/schedules/proposals/{proposal_id}/decide', headers=headers,
                        json={'confirmed': True})
    assert saved.status_code == 200
    schedule = saved.json()['data']['schedule']
    assert schedule['job_kind'] == 'medication'
    assert schedule['tz'] == 'Asia/Shanghai'
    def no_external(*args, **kwargs):
        raise AssertionError('in-app reminders must not send externally')
    monkeypatch.setattr('app.agent.proactive.jobs._try_deliver', no_external)
    result = runner.run_schedule(uid, schedule['id'], manual=True)
    assert result['ok'] and result['item_id']
    assert client.post(f'/api/schedules/proposals/{proposal_id}/decide', headers=headers,
                       json={'confirmed': True}).status_code == 422


def test_panel_cancel_and_once_creation(uid):
    client = RawTestClient(app)
    headers = {'X-User-Token': mint_user_token(uid)}
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    data = sample(job_kind='one_shot_reminder', trigger={'type': 'once', 'run_at': future})
    proposal = client.post('/api/schedules/proposals', headers=headers, json=data).json()['data']['proposal']
    assert client.post(f"/api/schedules/proposals/{proposal['id']}/decide", headers=headers,
                       json={'confirmed': False}).json()['data']['status'] == 'rejected'
    assert service.list_schedules(uid) == []
    assert client.post('/api/schedules/proposals', headers=headers, json=sample(tz='bad-zone')).status_code == 422
    assert client.post('/api/schedules/proposals', json=data).status_code == 401


def test_medication_chat_does_not_call_model_router(uid, monkeypatch):
    calls = []
    def no_model(*args, **kwargs):
        calls.append(True)
        raise AssertionError('deterministic medication creation must not require a model')
    monkeypatch.setattr('app.gateway.llm_gateway.chat_json', no_model)
    db.save_profile(uid, {'tz': 'shanxi'})
    response = RawTestClient(app).post('/api/chat', headers={'X-User-Token': mint_user_token(uid)},
                                      json={'message': '每天早上八点提醒我吃降压药'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['schedule_proposal']['preview']['trigger']['expr'] == '0 8 * * *'
    assert calls == []
