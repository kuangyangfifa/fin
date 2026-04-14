from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from models import db, Account, Transaction, NoteOption, Note1Option
from utils.excel_handler import export_transactions_to_excel, create_import_template, parse_excel_import
from utils.reporting import get_last_6_months_trends

transactions_bp = Blueprint('transactions', __name__)


def _build_transaction_query(start_date_str, end_date_str, account_id, keyword):
    """Build a filtered Transaction query."""
    query = Transaction.query

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(Transaction.date >= start_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(Transaction.date <= end_date)
        except ValueError:
            pass

    if account_id:
        query = query.filter(Transaction.account_id == account_id)

    if keyword:
        query = query.filter(
            db.or_(
                Transaction.summary.contains(keyword),
                Transaction.note1.contains(keyword),
                Transaction.note2.contains(keyword),
                Transaction.note3.contains(keyword),
                Transaction.note4.contains(keyword),
                Transaction.note5.contains(keyword)
            )
        )
    return query


def _build_total_query(start_date_str, end_date_str, account_id, keyword, column):
    """Build a filtered aggregate query for income or expense."""
    total_query = db.session.query(db.func.sum(column))

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            total_query = total_query.filter(Transaction.date >= start_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            total_query = total_query.filter(Transaction.date <= end_date)
        except ValueError:
            pass

    if account_id:
        total_query = total_query.filter(Transaction.account_id == account_id)

    if keyword:
        filter_condition = db.or_(
            Transaction.summary.contains(keyword),
            Transaction.note1.contains(keyword),
            Transaction.note2.contains(keyword),
            Transaction.note3.contains(keyword),
            Transaction.note4.contains(keyword),
            Transaction.note5.contains(keyword)
        )
        total_query = total_query.filter(filter_condition)

    return total_query


@transactions_bp.route('/transaction/add', methods=['GET', 'POST'])
@login_required
def add_transaction():
    """Add a new transaction."""
    if request.method == 'POST':
        date_str = request.form.get('date', '').strip()
        account_id = request.form.get('account_id')
        summary = request.form.get('summary', '').strip()
        income_str = request.form.get('income', '0').strip()
        expense_str = request.form.get('expense', '0').strip()
        note1 = request.form.get('note1', '').strip()
        note2 = request.form.get('note2', '').strip()
        note3 = request.form.get('note3', '').strip()
        note4 = request.form.get('note4', '').strip()
        note5 = request.form.get('note5', '').strip()

        if not date_str or not account_id:
            flash('日期和账户为必填项。', 'danger')
            return redirect(url_for('transactions.add_transaction'))

        try:
            trans_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('日期格式错误，请使用 YYYY-MM-DD 格式。', 'danger')
            return redirect(url_for('transactions.add_transaction'))

        try:
            income = float(income_str) if income_str else 0.0
            expense = float(expense_str) if expense_str else 0.0
        except ValueError:
            flash('收入或支出金额格式错误。', 'danger')
            return redirect(url_for('transactions.add_transaction'))

        if income < 0 or expense < 0:
            flash('收入和支出不能为负数。', 'danger')
            return redirect(url_for('transactions.add_transaction'))

        if income == 0 and expense == 0:
            flash('收入和支出不能同时为0。', 'danger')
            return redirect(url_for('transactions.add_transaction'))

        account = Account.query.get(account_id)
        if not account:
            flash('所选账户不存在。', 'danger')
            return redirect(url_for('transactions.add_transaction'))

        balance_before = Transaction.get_balance_before_transaction(account_id, trans_date)
        balance_after = balance_before + income - expense

        transaction = Transaction(
            date=trans_date,
            account_id=account_id,
            summary=summary,
            income=income,
            expense=expense,
            balance_after=balance_after,
            note1=note1,
            note2=note2,
            note3=note3,
            note4=note4,
            note5=note5,
            created_by=current_user.id
        )
        db.session.add(transaction)
        db.session.commit()

        Transaction.recalculate_balances(account_id, trans_date)

        flash('流水记录添加成功。', 'success')
        return redirect(url_for('transactions.add_transaction'))

    accounts = Account.query.order_by(Account.account_name).all()
    today = date.today().strftime('%Y-%m-%d')
    note_options = NoteOption.get_all_options_dict()
    note1_options = Note1Option.get_all_options_dict()
    return render_template('transaction_add.html', accounts=accounts, today=today,
                           note_options=note_options, note1_options=note1_options)


@transactions_bp.route('/transactions')
@login_required
def list_transactions():
    """List transactions with filters."""
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    account_id = request.args.get('account_id', '')
    keyword = request.args.get('keyword', '').strip()

    query = _build_transaction_query(start_date_str, end_date_str, account_id, keyword)
    query = query.order_by(Transaction.date.desc(), Transaction.id.desc())

    total_income = _build_total_query(start_date_str, end_date_str, account_id, keyword, Transaction.income).scalar() or 0
    total_expense = _build_total_query(start_date_str, end_date_str, account_id, keyword, Transaction.expense).scalar() or 0

    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('ITEMS_PER_PAGE', 50)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    transactions = pagination.items

    accounts = Account.query.order_by(Account.account_name).all()
    account_map = {a.id: a.account_name for a in accounts}
    note_options = NoteOption.get_all_options_dict()

    return render_template('transaction_list.html',
                           transactions=transactions,
                           pagination=pagination,
                           accounts=accounts,
                           account_map=account_map,
                           note_options=note_options,
                           total_income=total_income,
                           total_expense=total_expense,
                           start_date=start_date_str,
                           end_date=end_date_str,
                           selected_account=account_id,
                           keyword=keyword)


@transactions_bp.route('/transaction/edit/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def edit_transaction(transaction_id):
    """Edit an existing transaction."""
    transaction = Transaction.query.get_or_404(transaction_id)

    if request.method == 'POST':
        old_date = transaction.date
        old_account_id = transaction.account_id
        old_income = transaction.income
        old_expense = transaction.expense

        date_str = request.form.get('date', '').strip()
        account_id = request.form.get('account_id')
        summary = request.form.get('summary', '').strip()
        income_str = request.form.get('income', '0').strip()
        expense_str = request.form.get('expense', '0').strip()
        note1 = request.form.get('note1', '').strip()
        note2 = request.form.get('note2', '').strip()
        note3 = request.form.get('note3', '').strip()
        note4 = request.form.get('note4', '').strip()
        note5 = request.form.get('note5', '').strip()

        if not date_str or not account_id:
            flash('日期和账户为必填项。', 'danger')
            return redirect(url_for('transactions.edit_transaction', transaction_id=transaction_id))

        try:
            trans_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('日期格式错误，请使用 YYYY-MM-DD 格式。', 'danger')
            return redirect(url_for('transactions.edit_transaction', transaction_id=transaction_id))

        try:
            income = float(income_str) if income_str else 0.0
            expense = float(expense_str) if expense_str else 0.0
        except ValueError:
            flash('收入或支出金额格式错误。', 'danger')
            return redirect(url_for('transactions.edit_transaction', transaction_id=transaction_id))

        if income < 0 or expense < 0:
            flash('收入和支出不能为负数。', 'danger')
            return redirect(url_for('transactions.edit_transaction', transaction_id=transaction_id))

        if income == 0 and expense == 0:
            flash('收入和支出不能同时为0。', 'danger')
            return redirect(url_for('transactions.edit_transaction', transaction_id=transaction_id))

        account = Account.query.get(account_id)
        if not account:
            flash('所选账户不存在。', 'danger')
            return redirect(url_for('transactions.edit_transaction', transaction_id=transaction_id))

        transaction.date = trans_date
        transaction.account_id = account_id
        transaction.summary = summary
        transaction.income = income
        transaction.expense = expense
        transaction.note1 = note1
        transaction.note2 = note2
        transaction.note3 = note3
        transaction.note4 = note4
        transaction.note5 = note5
        transaction.updated_at = datetime.utcnow()

        db.session.commit()

        if old_account_id != int(account_id):
            Transaction.recalculate_balances(old_account_id, old_date)
            Transaction.recalculate_balances(int(account_id), trans_date)
        else:
            recalc_from = min(old_date, trans_date)
            Transaction.recalculate_balances(int(account_id), recalc_from)

        flash('流水记录更新成功。', 'success')
        return redirect(url_for('transactions.list_transactions'))

    accounts = Account.query.order_by(Account.account_name).all()
    note_options = NoteOption.get_all_options_dict()
    note1_options = Note1Option.get_all_options_dict()

    note1_parent = ''
    note1_child = transaction.note1 or ''
    for parent in note1_options.keys():
        prefix = parent + '-'
        if transaction.note1 and transaction.note1.startswith(prefix):
            note1_parent = parent
            note1_child = transaction.note1[len(prefix):]
            break

    return render_template('transaction_edit.html',
                           transaction=transaction,
                           accounts=accounts,
                           note_options=note_options,
                           note1_options=note1_options,
                           note1_parent=note1_parent,
                           note1_child=note1_child)


@transactions_bp.route('/transaction/delete/<int:transaction_id>', methods=['POST'])
@login_required
def delete_transaction(transaction_id):
    """Delete a transaction."""
    transaction = Transaction.query.get_or_404(transaction_id)
    account_id = transaction.account_id
    trans_date = transaction.date

    db.session.delete(transaction)
    db.session.commit()

    Transaction.recalculate_balances(account_id, trans_date)

    flash('流水记录已删除。', 'success')
    return redirect(url_for('transactions.list_transactions'))


@transactions_bp.route('/transactions/export')
@login_required
def export_transactions():
    """Export transactions to Excel."""
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    account_id = request.args.get('account_id', '')
    keyword = request.args.get('keyword', '').strip()

    query = _build_transaction_query(start_date_str, end_date_str, account_id, keyword)
    query = query.order_by(Transaction.date, Transaction.id)
    transactions = query.all()

    accounts = Account.query.all()
    account_map = {a.id: a.account_name for a in accounts}

    output = export_transactions_to_excel(transactions, account_map)

    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"transactions_{timestamp}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@transactions_bp.route('/transactions/import', methods=['GET', 'POST'])
@login_required
def import_transactions():
    """Import transactions from Excel."""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('请选择要上传的文件。', 'danger')
            return redirect(url_for('transactions.import_transactions'))

        file = request.files['file']
        if file.filename == '':
            flash('请选择要上传的文件。', 'danger')
            return redirect(url_for('transactions.import_transactions'))

        if not file.filename.endswith(('.xlsx', '.xls')):
            flash('请上传 Excel 文件 (.xlsx 或 .xls)。', 'danger')
            return redirect(url_for('transactions.import_transactions'))

        accounts = Account.query.all()
        account_name_to_id = {a.account_name: a.id for a in accounts}

        if not accounts:
            flash('系统中没有账户，请先创建至少一个账户。', 'danger')
            return redirect(url_for('transactions.import_transactions'))

        success, result = parse_excel_import(file, account_name_to_id)

        if not success:
            for error in result:
                flash(error, 'danger')
            return redirect(url_for('transactions.import_transactions'))

        transactions_data = result
        imported_count = 0

        try:
            for data in transactions_data:
                balance_before = Transaction.get_balance_before_transaction(
                    data['account_id'], data['date']
                )
                balance_after = balance_before + data['income'] - data['expense']

                transaction = Transaction(
                    date=data['date'],
                    account_id=data['account_id'],
                    summary=data['summary'],
                    income=data['income'],
                    expense=data['expense'],
                    balance_after=balance_after,
                    note1=data.get('note1', ''),
                    note2=data.get('note2', ''),
                    note3=data.get('note3', ''),
                    note4=data.get('note4', ''),
                    note5=data.get('note5', ''),
                    created_by=current_user.id
                )
                db.session.add(transaction)
                imported_count += 1

            db.session.commit()

            for acc_id in set(t['account_id'] for t in transactions_data):
                Transaction.recalculate_balances(acc_id)

            flash(f'成功导入 {imported_count} 条流水记录。', 'success')
            return redirect(url_for('transactions.list_transactions'))

        except Exception as e:
            db.session.rollback()
            flash(f'导入过程中出错：{str(e)}', 'danger')
            return redirect(url_for('transactions.import_transactions'))

    return render_template('transaction_import.html')


@transactions_bp.route('/transactions/import/template')
@login_required
def download_import_template():
    """Download Excel import template."""
    output = create_import_template()
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='transaction_import_template.xlsx'
    )
