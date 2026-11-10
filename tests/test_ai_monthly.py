"""AI 月度分析报告测试：全部使用假驱动，不发起真实大模型请求。"""

from datetime import date
from unittest.mock import patch

import pytest

from models import db, Transaction

DATA_MONTH = '2026-04'


class _FakeProvider:
    model = 'fake-model'

    def __init__(self, calls=None, error=None):
        self.calls = calls if calls is not None else []
        self.error = error

    def chat(self, messages, max_tokens=1024, system=None):
        if self.error:
            raise self.error
        self.calls.append({
            'prompt': messages[0]['content'],
            'max_tokens': max_tokens,
            'system': system or '',
        })
        return '## 一、经营概览\n\n- 本月收入 **1000.00** 元\n\n### 建议\n1. 控制成本\n'


def _login(client):
    return client.post('/login', data={'username': 'admin', 'password': 'admin123'})


@pytest.fixture
def isolated_cache(app, tmp_path, monkeypatch):
    """把报告缓存重定向到临时目录，避免测试写真实 instance/ 目录。"""
    monkeypatch.setattr(app, 'instance_path', str(tmp_path))
    return tmp_path


@pytest.fixture
def seeded_month(app, sample_account, isolated_cache):
    with app.app_context():
        db.session.add(Transaction(
            date=date(2026, 4, 5), account_id=sample_account.id,
            summary='服务收入', income=1000, expense=0,
            note1='项目A-开发', note2='主营收入',
        ))
        db.session.add(Transaction(
            date=date(2026, 4, 20), account_id=sample_account.id,
            summary='材料采购', income=0, expense=300,
            note1='项目A-开发', note2='采购',
        ))
        db.session.commit()
    return isolated_cache


def test_page_defaults_to_latest_month_with_data(client, admin_user, seeded_month):
    _login(client)
    html = client.get('/reports/ai-monthly').get_data(as_text=True)
    assert 'value="2026-04"' in html
    assert 'LEXUE财务管理系统' in html
    assert '数据覆盖：2026-04-05 至 2026-04-20' in html
    assert '未配置 AI_PROVIDER' in html


@pytest.mark.parametrize('month', ['', 'abc', '2026-13', '2026-4', '2026/04'])
def test_invalid_month_returns_400(client, admin_user, isolated_cache, month):
    _login(client)
    resp = client.post('/reports/ai-monthly', json={'month': month})
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False


def test_empty_month_short_circuits_without_calling_model(client, admin_user, seeded_month):
    """空月份不得把全 0 数据交给模型，否则模型会凭空编造报告。"""
    _login(client)
    with patch('routes.reports.get_ai_provider',
               side_effect=AssertionError('空月份不应调用模型')):
        resp = client.post('/reports/ai-monthly', json={'month': '2030-01'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['no_data'] is True
    assert data['success'] is True
    assert DATA_MONTH in data['message']
    assert data['available_months'] == [DATA_MONTH]


def test_generate_report_and_persist_cache(client, admin_user, seeded_month):
    _login(client)
    calls = []
    provider = _FakeProvider(calls)

    with patch('routes.reports.get_ai_provider', return_value=provider):
        resp = client.post('/reports/ai-monthly', json={'month': DATA_MONTH})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['cached'] is False
    assert data['model'] == 'fake-model'
    assert data['transaction_count'] == 2
    assert '经营概览' in data['analysis']
    assert '¥1,000.00' in calls[0]['prompt']
    assert calls[0]['max_tokens'] == 3000
    assert '不得编造' in calls[0]['system']
    assert (seeded_month / 'ai_reports' / f'{DATA_MONTH}.json').exists()


def test_cached_report_skips_model(client, admin_user, seeded_month):
    _login(client)
    calls = []
    with patch('routes.reports.get_ai_provider', return_value=_FakeProvider(calls)):
        first = client.post('/reports/ai-monthly', json={'month': DATA_MONTH}).get_json()
    assert first['cached'] is False

    with patch('routes.reports.get_ai_provider',
               side_effect=AssertionError('命中缓存时不应调用模型')):
        resp = client.post('/reports/ai-monthly', json={'month': DATA_MONTH})
    assert resp.status_code == 200
    assert resp.get_json()['cached'] is True
    assert len(calls) == 1


def test_force_regenerates_report(client, admin_user, seeded_month):
    _login(client)
    calls = []
    with patch('routes.reports.get_ai_provider', return_value=_FakeProvider(calls)):
        client.post('/reports/ai-monthly', json={'month': DATA_MONTH})
        resp = client.post('/reports/ai-monthly',
                           json={'month': DATA_MONTH, 'force': True})
    assert resp.status_code == 200
    assert resp.get_json()['cached'] is False
    assert len(calls) == 2


def test_missing_provider_returns_clear_error(client, admin_user, seeded_month):
    _login(client)
    resp = client.post('/reports/ai-monthly', json={'month': DATA_MONTH})
    assert resp.status_code == 503
    assert 'AI 服务未配置' in resp.get_json()['error']


def test_internal_error_does_not_leak_details(client, admin_user, seeded_month):
    _login(client)
    provider = _FakeProvider(error=RuntimeError('sk-secret-DO-NOT-LEAK'))
    with patch('routes.reports.get_ai_provider', return_value=provider):
        resp = client.post('/reports/ai-monthly', json={'month': DATA_MONTH})
    assert resp.status_code == 500
    error = resp.get_json()['error']
    assert 'sk-secret' not in error
    assert '服务器内部错误' in error


def test_prompt_section_numbers_are_sequential():
    from routes.reports import _build_analysis_prompt

    summary = {'income': 1000.0, 'expense': 300.0, 'net': 700.0, 'transaction_count': 2}
    prev = {'income': 0.0, 'expense': 0.0, 'net': 0.0}
    sample = [{'value': '项目A', 'income': 1000.0, 'expense': 300.0,
               'net': 700.0, 'total': 1300.0}]
    prompt = _build_analysis_prompt(
        '2026-04', summary, prev,
        [{'name': '现金', 'income': 1000.0, 'expense': 300.0, 'net': 700.0}],
        sample, sample, sample, sample, sample,
    )
    assert '### 一、' in prompt
    assert '### 二、' in prompt
    assert '### 三、' in prompt
    assert '### 七、' in prompt
    assert '不得编造' in prompt
