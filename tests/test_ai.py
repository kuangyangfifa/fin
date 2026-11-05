from datetime import date

from models import db, Transaction


def test_ai_chat_session_and_message_flow(client, admin_user, sample_account, app):
    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    })

    with app.app_context():
        db.session.add(Transaction(
            date=date.today().replace(day=1),
            account_id=sample_account.id,
            summary='项目A 收入',
            income=1000,
            expense=0,
            note1='项目A-开发',
            note2='主营收入',
            note3='合同款',
        ))
        db.session.add(Transaction(
            date=date.today().replace(day=2),
            account_id=sample_account.id,
            summary='项目A 支出',
            income=0,
            expense=200,
            note1='项目A-开发',
            note2='采购',
            note3='材料',
        ))
        db.session.commit()

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
