from datetime import date
from flask import Blueprint, render_template
from flask_login import login_required
from models import db, Account, Transaction
from utils.reporting import get_last_6_months_trends

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def index():
    """Dashboard - account overview and statistics."""
    accounts = Account.query.all()
    account_data = []
    total_balance = 0

    for account in accounts:
        balance = account.get_current_balance()
        account_data.append({
            'id': account.id,
            'name': account.account_name,
            'balance': balance
        })
        total_balance += balance

    today = date.today()
    first_day_of_month = today.replace(day=1)

    month_income = db.session.query(db.func.sum(Transaction.income)).\
        filter(Transaction.date >= first_day_of_month,
               Transaction.date <= today).scalar() or 0

    month_expense = db.session.query(db.func.sum(Transaction.expense)).\
        filter(Transaction.date >= first_day_of_month,
               Transaction.date <= today).scalar() or 0

    recent_transactions = Transaction.query.\
        order_by(Transaction.date.desc(), Transaction.id.desc()).limit(10).all()

    account_map = {a.id: a.account_name for a in accounts}
    month_trends = get_last_6_months_trends()

    return render_template('dashboard.html',
                           accounts=account_data,
                           total_balance=total_balance,
                           month_income=month_income,
                           month_expense=month_expense,
                           recent_transactions=recent_transactions,
                           account_map=account_map,
                           month_trends=month_trends)
