from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Account, Transaction

accounts_bp = Blueprint('accounts', __name__)


@accounts_bp.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    """Account management - list and add accounts."""
    if request.method == 'POST':
        account_name = request.form.get('account_name', '').strip()
        initial_balance_str = request.form.get('initial_balance', '0')

        if not account_name:
            flash('账户名称不能为空。', 'danger')
            return redirect(url_for('accounts.accounts'))

        if Account.query.filter_by(account_name=account_name).first():
            flash(f'账户 "{account_name}" 已存在。', 'danger')
            return redirect(url_for('accounts.accounts'))

        try:
            initial_balance = float(initial_balance_str) if initial_balance_str else 0.0
        except ValueError:
            flash('期初余额格式错误。', 'danger')
            return redirect(url_for('accounts.accounts'))

        new_account = Account(
            account_name=account_name,
            initial_balance=initial_balance,
            created_by=current_user.id
        )
        db.session.add(new_account)
        db.session.commit()

        flash(f'账户 "{account_name}" 创建成功。', 'success')
        return redirect(url_for('accounts.accounts'))

    all_accounts = Account.query.all()
    account_data = []

    for account in all_accounts:
        transaction_count = Transaction.query.filter_by(account_id=account.id).count()
        current_balance = account.get_current_balance()

        account_data.append({
            'id': account.id,
            'name': account.account_name,
            'initial_balance': account.initial_balance,
            'current_balance': current_balance,
            'transaction_count': transaction_count,
            'created_at': account.created_at
        })

    return render_template('accounts.html', accounts=account_data)


@accounts_bp.route('/account/<int:account_id>/edit', methods=['POST'])
@login_required
def edit_account(account_id):
    """Edit account name and initial balance."""
    account = Account.query.get_or_404(account_id)
    new_name = request.form.get('new_name', '').strip()
    new_initial_balance_str = request.form.get('new_initial_balance', '0')

    if not new_name:
        flash('账户名称不能为空。', 'danger')
        return redirect(url_for('accounts.accounts'))

    existing = Account.query.filter_by(account_name=new_name).first()
    if existing and existing.id != account_id:
        flash(f'账户名称 "{new_name}" 已被使用。', 'danger')
        return redirect(url_for('accounts.accounts'))

    try:
        new_initial_balance = float(new_initial_balance_str) if new_initial_balance_str else 0.0
    except ValueError:
        flash('期初余额格式错误。', 'danger')
        return redirect(url_for('accounts.accounts'))

    old_name = account.account_name
    old_initial_balance = account.initial_balance
    account.account_name = new_name
    account.initial_balance = new_initial_balance
    db.session.commit()

    if old_initial_balance != new_initial_balance:
        Transaction.recalculate_balances(account_id)
        flash(f'账户 "{old_name}" 已更新为 "{new_name}"，期初余额已调整，所有流水余额已重新计算。', 'success')
    else:
        flash(f'账户已从 "{old_name}" 重命名为 "{new_name}"。', 'success')
    return redirect(url_for('accounts.accounts'))


@accounts_bp.route('/account/<int:account_id>/delete', methods=['POST'])
@login_required
def delete_account(account_id):
    """Delete an account and all its transactions."""
    account = Account.query.get_or_404(account_id)

    transaction_count = Transaction.query.filter_by(account_id=account_id).count()
    if transaction_count > 0:
        flash(f'无法删除账户 "{account.account_name}"，该账户下还有 {transaction_count} 条流水记录。请先删除所有流水记录。', 'danger')
        return redirect(url_for('accounts.accounts'))

    account_name = account.account_name
    db.session.delete(account)
    db.session.commit()

    flash(f'账户 "{account_name}" 已删除。', 'success')
    return redirect(url_for('accounts.accounts'))
