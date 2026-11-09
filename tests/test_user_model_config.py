"""BYOK configuration must verify the submitted model before replacing a working key."""
import uuid

import httpx
import pytest

from app import user_model
from app.auth import mint_user_token
from app.data_access import user_scope
from app.gateway import providers
from app.main import app
from tests.conftest import RawTestClient


@pytest.fixture
def setup_model_probe():
    uid = 'model-probe-' + uuid.uuid4().hex
    headers = {'X-User-Token': mint_user_token(uid)}
    seen = []
    outcome = {'status': 200}

    def handler(request):
        seen.append(request)
        if outcome.get('timeout'):
            raise httpx.ReadTimeout('synthetic timeout', request=request)
        if outcome['status'] != 200:
            return httpx.Response(outcome['status'], json={'error': {'message': 'upstream echoed sk-synthetic-private-key'}})
        return httpx.Response(200, json={'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]})

    providers.set_transport_factory(lambda: httpx.MockTransport(handler))
    try:
        yield RawTestClient(app), uid, headers, seen, outcome
    finally:
        providers.set_transport_factory(None)
        user_model.clear_current()


def payload(**updates):
    return {'base_url': 'https://model.example.test/v1', 'model': 'synthetic-model',
            'api_key': 'sk-synthetic-private-key', 'vendor': 'custom', **updates}


def test_success_probes_exact_model_then_saves_encrypted_config(setup_model_probe):
    client, uid, headers, seen, _ = setup_model_probe
    response = client.put('/api/model/config', headers=headers, json=payload())
    assert response.status_code == 200
    assert response.json()['data']['configured'] is True
    assert len(seen) == 1
    assert str(seen[0].url) == 'https://model.example.test/v1/chat/completions'
    import json
    assert json.loads(seen[0].content)['model'] == 'synthetic-model'
    assert 'sk-synthetic-private-key' not in response.text
    with user_scope(uid):
        assert user_model.get_config(uid)['model'] == 'synthetic-model'


@pytest.mark.parametrize('status,reason', [(401, 'Key'), (403, '权限'), (404, '不存在'),
                                           (429, '额度'), (400, '拒绝请求'), (500, '暂时异常')])
def test_failure_returns_safe_reason_and_preserves_previous_config(setup_model_probe, status, reason):
    client, uid, headers, seen, outcome = setup_model_probe
    with user_scope(uid):
        user_model.save_config(uid, 'https://old.example.test/v1', 'working-model', 'sk-previous-test-key')
    outcome['status'] = status
    response = client.put('/api/model/config', headers=headers, json=payload())
    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'model_connection_failed'
    assert reason in response.json()['detail']['message']
    assert len(seen) == 1  # No retry and no fallback may disguise a failed user config.
    assert 'sk-synthetic-private-key' not in response.text
    with user_scope(uid):
        assert user_model.get_config(uid)['model'] == 'working-model'


def test_timeout_reports_reason_without_saving(setup_model_probe):
    client, uid, headers, _, outcome = setup_model_probe
    outcome['timeout'] = True
    response = client.put('/api/model/config', headers=headers, json=payload())
    assert response.status_code == 400
    assert '超时' in response.json()['detail']['message']
    with user_scope(uid):
        assert user_model.get_config(uid) is None


def test_full_endpoint_is_rejected_before_sending_key(setup_model_probe):
    client, _, headers, seen, _ = setup_model_probe
    response = client.put('/api/model/config', headers=headers,
                          json=payload(base_url='https://model.example.test/kimi/chat/completions'))
    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'invalid_config'
    assert '基础地址' in response.json()['detail']['message']
    assert not seen


def test_missing_session_cannot_probe_model(setup_model_probe):
    client, _, _, seen, _ = setup_model_probe
    assert client.put('/api/model/config', json=payload()).status_code == 401
    assert not seen
