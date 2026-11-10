import json
from datetime import date
from unittest.mock import patch

import pytest

from models import db, Transaction
from utils.ai_analyzer import parse_date_expression


def _login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password})


def _seed_transactions(account_id):
    """Insert two transactions in the current month for chart assertions."""
    db.session.add(Transaction(
        date=date.today().replace(day=1),
        account_id=account_id,
        summary='项目A 收入',
        income=1000,
        expense=0,
        note1='项目A-开发',
        note2='主营收入',
        note3='合同款',
    ))
    db.session.add(Transaction(
        date=date.today().replace(day=2),
        account_id=account_id,
        summary='项目A 支出',
        income=0,
        expense=200,
        note1='项目A-开发',
        note2='采购',
        note3='材料',
    ))
    db.session.commit()


def test_ai_chat_session_and_message_flow(client, admin_user, sample_account, app):
    _login(client)

    with app.app_context():
        _seed_transactions(sample_account.id)

    resp = client.post('/ai/sessions', json={'title': '新对话'})
    assert resp.status_code == 201
    session_id = resp.get_json()['id']

    resp = client.post(f'/ai/chat/{session_id}', json={'message': '本月各项目收入是多少？'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['chart_type'] == 'bar'
    assert 'labels' in data['chart_data']
    assert any('项目A' in (x or '') for x in data['chart_data']['labels'])

    resp = client.post(f'/ai/chat/{session_id}', json={'message': '支出结构分析'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['chart_type'] == 'pie'
    assert 'datasets' in data['chart_data']

    history = client.get(f'/ai/sessions/{session_id}').get_json()['messages']
    assert [m['role'] for m in history] == ['user', 'assistant', 'user', 'assistant']

    assert client.delete(f'/ai/sessions/{session_id}').status_code == 200


@pytest.mark.parametrize('expr, expected', [
    ('2024-1-1', (date(2024, 1, 1), date(2024, 1, 1))),
    ('2024-01-01', (date(2024, 1, 1), date(2024, 1, 1))),
    ('2024/3/5', (date(2024, 3, 5), date(2024, 3, 5))),
    ('2024年1月1日', (date(2024, 1, 1), date(2024, 1, 1))),
    ('2024-1-1至2024-3-31', (date(2024, 1, 1), date(2024, 3, 31))),
    ('2024年1月1日至2024年3月31日', (date(2024, 1, 1), date(2024, 3, 31))),
    ('2024年3月', (date(2024, 3, 1), date(2024, 3, 31))),
    ('2024年', (date(2024, 1, 1), date(2024, 12, 31))),
    ('2024-13-01', (None, None)),
    ('不是日期', (None, None)),
])
def test_parse_date_expression(expr, expected):
    """日期解析需兼容非补零、中文单日与中文区间。"""
    assert parse_date_expression(expr) == expected


def test_parse_date_expression_relative():
    start, end = parse_date_expression('近6个月')
    assert start < end <= date.today()
    assert (end - start).days in (179, 180, 181)


def test_ai_status_is_isolated_from_production_env(client, admin_user):
    """测试环境不得继承 .env 中的 AI_PROVIDER，否则会真实调用大模型。"""
    _login(client)
    resp = client.get('/ai/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['provider'] == ''
    assert data['state'] == 'disabled'
    assert data['api_key_configured'] is False


def test_ai_pages_require_admin(client, regular_user):
    _login(client, 'user', 'user123')
    assert client.get('/ai').status_code == 302
    assert client.get('/ai/status').status_code == 302
    assert client.post('/ai/sessions', json={'title': 'x'}).status_code == 302


def test_ai_chat_without_any_transaction(client, admin_user, sample_account):
    """空库时给出明确提示，而不是让模型生成一份数据缺失的长报告。"""
    _login(client)
    sid = client.post('/ai/sessions', json={'title': '空库'}).get_json()['id']
    resp = client.post(f'/ai/chat/{sid}', json={'message': '各项目收入汇总'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert '尚无交易数据' in data['reply']


def test_ai_chat_defaults_to_latest_month_with_data(client, admin_user, sample_account, app):
    """数据全部落在历史月份时，未指定日期的提问应自动按最近有数据月份统计。"""
    _login(client)
    with app.app_context():
        db.session.add(Transaction(
            date=date(2024, 2, 10),
            account_id=sample_account.id,
            summary='历史收入',
            income=500,
            expense=0,
            note1='项目B-实施',
        ))
        db.session.commit()

    sid = client.post('/ai/sessions', json={'title': '默认月份'}).get_json()['id']
    resp = client.post(f'/ai/chat/{sid}', json={'message': '各项目收入汇总'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['chart_type'] == 'bar'
    assert any('项目B' in (x or '') for x in data['chart_data']['labels'])
    assert '2024-02' in (data.get('date_range_note') or '')


class _RecordingProvider:
    """意图识别用的假驱动：记录送入模型的消息，不发起任何网络请求。"""

    def __init__(self):
        self.intent_calls = []

    def chat(self, messages, max_tokens=1024, system=None):
        if system and '识别用户的意图' in system:
            self.intent_calls.append([dict(m) for m in messages])
            return json.dumps({'intent_type': 'project_income', 'parameters': {}})
        return '这是模拟的分析结论。'

    def parse_json_response(self, text):
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return None


def test_ai_chat_history_has_no_duplicate_current_question(
    client, admin_user, sample_account, app
):
    """路由先落库用户消息，历史回放时必须剔除当前提问。"""
    _login(client)
    with app.app_context():
        _seed_transactions(sample_account.id)

    provider = _RecordingProvider()
    sid = client.post('/ai/sessions', json={'title': '去重'}).get_json()['id']
    question = '各项目收入汇总'

    with patch('utils.ai_analyzer.get_ai_provider', return_value=provider):
        assert client.post(f'/ai/chat/{sid}', json={'message': question}).status_code == 200
        assert client.post(f'/ai/chat/{sid}', json={'message': question}).status_code == 200

    assert len(provider.intent_calls) == 2
    for messages in provider.intent_calls:
        current = [m for m in messages if m['content'].startswith(question)]
        assert len(current) == 1, '当前提问在送入模型的消息中重复出现'

    second_round = provider.intent_calls[1]
    assert second_round[0]['role'] == 'user'
    assert any(m['role'] == 'assistant' for m in second_round)
