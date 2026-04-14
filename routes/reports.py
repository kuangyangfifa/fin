from datetime import datetime, date
from flask import Blueprint, render_template, request
from flask_login import login_required
from models import db, Account, Transaction, NoteOption
from utils.reporting import month_format, year_format

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/reports')
@login_required
def reports():
    """Report analysis page."""
    return render_template('reports.html')


@reports_bp.route('/reports/daily')
@login_required
def report_daily():
    """Daily report analysis - show each account's status per date."""
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    if not start_date_str:
        start_date_str = date.today().replace(day=1).strftime('%Y-%m-%d')
    if not end_date_str:
        end_date_str = date.today().strftime('%Y-%m-%d')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = date.today()

    all_accounts = Account.query.order_by(Account.account_name).all()
    account_map = {a.id: a.account_name for a in all_accounts}

    query = db.session.query(
        Transaction.date,
        Transaction.account_id,
        db.func.sum(Transaction.income).label('total_income'),
        db.func.sum(Transaction.expense).label('total_expense')
    ).filter(
        Transaction.date >= start_date,
        Transaction.date <= end_date
    ).group_by(Transaction.date, Transaction.account_id).order_by(Transaction.date, Transaction.account_id)

    daily_data = query.all()

    dates_data = {}
    for row in daily_data:
        date_key = row.date.strftime('%Y-%m-%d')
        if date_key not in dates_data:
            dates_data[date_key] = {
                'date': row.date,
                'accounts': {},
                'total_income': 0,
                'total_expense': 0
            }
        dates_data[date_key]['accounts'][row.account_id] = {
            'account_name': account_map.get(row.account_id, '未知'),
            'income': row.total_income or 0,
            'expense': row.total_expense or 0,
            'net': (row.total_income or 0) - (row.total_expense or 0)
        }
        dates_data[date_key]['total_income'] += row.total_income or 0
        dates_data[date_key]['total_expense'] += row.total_expense or 0

    return render_template('report_daily.html',
                           dates_data=dates_data,
                           accounts=all_accounts,
                           start_date=start_date_str,
                           end_date=end_date_str)


@reports_bp.route('/reports/monthly')
@login_required
def report_monthly():
    """Monthly report analysis - show all accounts per month."""
    year = request.args.get('year', date.today().year, type=int)

    all_accounts = Account.query.order_by(Account.account_name).all()
    account_map = {a.id: a.account_name for a in all_accounts}

    year_expr = year_format(Transaction.date)
    month_expr = month_format(Transaction.date)

    query = db.session.query(
        month_expr.label('month'),
        Transaction.account_id,
        db.func.sum(Transaction.income).label('total_income'),
        db.func.sum(Transaction.expense).label('total_expense')
    ).filter(
        year_expr == str(year)
    ).group_by(month_expr, Transaction.account_id).order_by(month_expr, Transaction.account_id)

    monthly_data = query.all()

    months_data = {}
    for row in monthly_data:
        month_key = row.month
        if month_key not in months_data:
            months_data[month_key] = {
                'month': row.month,
                'accounts': {},
                'total_income': 0,
                'total_expense': 0
            }
        months_data[month_key]['accounts'][row.account_id] = {
            'account_name': account_map.get(row.account_id, '未知'),
            'income': row.total_income or 0,
            'expense': row.total_expense or 0,
            'net': (row.total_income or 0) - (row.total_expense or 0)
        }
        months_data[month_key]['total_income'] += row.total_income or 0
        months_data[month_key]['total_expense'] += row.total_expense or 0

    return render_template('report_monthly.html',
                           months_data=months_data,
                           accounts=all_accounts,
                           year=year)


@reports_bp.route('/reports/by-note')
@login_required
def report_by_note():
    """Report analysis by note fields."""
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    note_field = request.args.get('note_field', 'note1')
    period_type = request.args.get('period_type', 'daily')

    if not start_date_str:
        start_date_str = date.today().replace(day=1).strftime('%Y-%m-%d')
    if not end_date_str:
        end_date_str = date.today().strftime('%Y-%m-%d')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = date.today()

    if note_field not in ['note1', 'note2', 'note3', 'note4', 'note5']:
        note_field = 'note1'

    if period_type == 'monthly':
        query = db.session.query(
            month_format(Transaction.date).label('period'),
            getattr(Transaction, note_field).label('note_value'),
            db.func.sum(Transaction.income).label('total_income'),
            db.func.sum(Transaction.expense).label('total_expense')
        ).filter(
            Transaction.date >= start_date,
            Transaction.date <= end_date
        )
    else:
        query = db.session.query(
            Transaction.date.label('period'),
            getattr(Transaction, note_field).label('note_value'),
            db.func.sum(Transaction.income).label('total_income'),
            db.func.sum(Transaction.expense).label('total_expense')
        ).filter(
            Transaction.date >= start_date,
            Transaction.date <= end_date
        )

    query = query.group_by('period', 'note_value').order_by('period', db.desc(db.func.sum(Transaction.income + Transaction.expense)))
    report_data = query.all()

    periods = {}
    for row in report_data:
        period_key = row.period
        if period_key not in periods:
            periods[period_key] = []
        periods[period_key].append({
            'note_value': row.note_value or '(空)',
            'income': row.total_income or 0,
            'expense': row.total_expense or 0,
            'net': (row.total_income or 0) - (row.total_expense or 0)
        })

    note_options = NoteOption.get_options_for_field(note_field)

    return render_template('report_by_note.html',
                           periods=periods,
                           note_field=note_field,
                           note_options=note_options,
                           period_type=period_type,
                           start_date=start_date_str,
                           end_date=end_date_str)


