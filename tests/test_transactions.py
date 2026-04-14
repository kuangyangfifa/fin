from datetime import date
from io import BytesIO
from models import db, Account, Transaction
from utils.excel_handler import create_import_template, parse_excel_import


def _text(response):
    return response.data.decode('utf-8')


def test_recalculate_balances(app, sample_account):
    with app.app_context():
        acc_id = sample_account.id
        t1 = Transaction(date=date(2024, 1, 1), account_id=acc_id, income=100, expense=0, balance_after=1100)
        t2 = Transaction(date=date(2024, 1, 2), account_id=acc_id, income=0, expense=50, balance_after=1050)
        db.session.add_all([t1, t2])
        db.session.commit()

        Transaction.recalculate_balances(acc_id)

        t1_db = Transaction.query.get(t1.id)
        t2_db = Transaction.query.get(t2.id)
        assert t1_db.balance_after == 1100.0
        assert t2_db.balance_after == 1050.0


def test_get_balance_before_transaction(app, sample_account):
    with app.app_context():
        acc_id = sample_account.id
        t1 = Transaction(date=date(2024, 1, 1), account_id=acc_id, income=100, expense=0, balance_after=1100)
        db.session.add(t1)
        db.session.commit()

        balance = Transaction.get_balance_before_transaction(acc_id, date(2024, 1, 2))
        assert balance == 1100.0


def test_parse_excel_import_success():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(['日期', '账户名称', '摘要', '收入', '支出', '项目', '学费/退费专用', '对象', '报销专用', '特殊说明事项'])
    ws.append(['2024-01-15', 'Cash', 'Test income', 500, 0, '', '', '', '', ''])
    ws.append(['2024-01-16', 'Cash', 'Test expense', 0, 200, '', '', '', '', ''])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    success, result = parse_excel_import(output, {'Cash': 1})
    assert success is True
    assert len(result) == 2
    assert result[0]['income'] == 500.0
    assert result[0]['expense'] == 0.0


def test_add_and_list_transaction(client, admin_user, sample_account):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})

    response = client.post('/transaction/add', data={
        'date': '2024-01-15',
        'account_id': sample_account.id,
        'summary': 'Salary',
        'income': '3000',
        'expense': '0',
        'note1': '',
        'note2': '',
        'note3': '',
        'note4': '',
        'note5': ''
    }, follow_redirects=True)
    assert '流水记录添加成功' in _text(response)

    response = client.get('/transactions')
    assert 'Salary' in _text(response)
