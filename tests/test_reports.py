from datetime import date
from models import db, Account, Transaction


def _text(response):
    return response.data.decode('utf-8')


def test_report_monthly_sqlite(client, admin_user, app):
    """Monthly report should work on SQLite after cross-db fix."""
    with app.app_context():
        acc = Account(account_name='TestAcc', initial_balance=0)
        db.session.add(acc)
        db.session.flush()
        db.session.add(Transaction(
            date=date(2024, 3, 15), account_id=acc.id,
            income=1000, expense=0, balance_after=1000
        ))
        db.session.add(Transaction(
            date=date(2024, 3, 20), account_id=acc.id,
            income=0, expense=200, balance_after=800
        ))
        db.session.commit()

    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    response = client.get('/reports/monthly?year=2024')
    assert response.status_code == 200
    assert '2024-03' in _text(response)


def test_report_by_note_monthly(client, admin_user, app):
    with app.app_context():
        acc = Account(account_name='TestAcc2', initial_balance=0)
        db.session.add(acc)
        db.session.flush()
        db.session.add(Transaction(
            date=date(2024, 4, 10), account_id=acc.id,
            income=500, expense=0, balance_after=500,
            note1='ProjectA'
        ))
        db.session.commit()

    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    response = client.get('/reports/by-note?note_field=note1&period_type=monthly&start_date=2024-04-01&end_date=2024-04-30')
    assert response.status_code == 200
    assert 'ProjectA' in _text(response)
