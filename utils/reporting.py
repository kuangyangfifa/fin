from datetime import date
from flask import current_app
from sqlalchemy import func, extract
from models import db, Transaction


def month_format(expr):
    """Cross-database month formatting as 'YYYY-MM'.

    SQLite uses strftime, PostgreSQL uses to_char.
    """
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if uri.startswith('sqlite'):
        return func.strftime('%Y-%m', expr)
    return func.to_char(expr, 'YYYY-MM')


def year_format(expr):
    """Cross-database year formatting as 'YYYY'.

    SQLite uses strftime, PostgreSQL uses to_char/extract.
    """
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if uri.startswith('sqlite'):
        return func.strftime('%Y', expr)
    return func.to_char(expr, 'YYYY')


def get_last_6_months_trends():
    """Get income/expense trends for the last 6 months.

    Returns a list of dicts: [{'month': 'YYYY-MM', 'income': float, 'expense': float}, ...]
    """
    today = date.today()
    month_trends = []
    for i in range(5, -1, -1):
        m = (today.month - i - 1) % 12 + 1
        y = today.year + (today.month - i - 1) // 12
        inc_sum = db.session.query(func.sum(Transaction.income)).filter(
            extract('year', Transaction.date) == y,
            extract('month', Transaction.date) == m
        ).scalar() or 0
        exp_sum = db.session.query(func.sum(Transaction.expense)).filter(
            extract('year', Transaction.date) == y,
            extract('month', Transaction.date) == m
        ).scalar() or 0
        month_trends.append({
            'month': f"{y}-{m:02d}",
            'income': float(inc_sum),
            'expense': float(exp_sum)
        })
    return month_trends
