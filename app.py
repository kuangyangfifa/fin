import os
import click
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename

from config import config
from models import db, User, Account, Transaction
from utils.excel_handler import export_transactions_to_excel, create_import_template, parse_excel_import

# Initialize Flask app
def create_app(config_name=None):
    """Application factory pattern."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize extensions
    db.init_app(app)

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = '请先登录以访问此页面。'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Create database tables
    with app.app_context():
        db.create_all()

    # Add context processor to provide current datetime to all templates
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    # Register routes
    register_routes(app)

    # Register CLI commands
    register_cli_commands(app)

    return app


def register_routes(app):
    """Register all application routes."""

    # ==================== Authentication Routes ====================

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """User login."""
        if current_user.is_authenticated:
            return redirect(url_for('index'))

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            if not username or not password:
                flash('请输入用户名和密码。', 'danger')
                return render_template('login.html')

            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user, remember=True)
                next_page = request.args.get('next')
                flash(f'欢迎回来，{user.username}！', 'success')
                return redirect(next_page if next_page else url_for('index'))
            else:
                flash('用户名或密码错误。', 'danger')

        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        """User logout."""
        logout_user()
        flash('您已成功退出登录。', 'info')
        return redirect(url_for('login'))

    # ==================== Dashboard Routes ====================

    @app.route('/')
    @login_required
    def index():
        """Dashboard - account overview and statistics."""
        # Get all accounts with their current balances
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

        # Get current month's statistics
        today = date.today()
        first_day_of_month = today.replace(day=1)

        month_income = db.session.query(db.func.sum(Transaction.income)).\
            filter(Transaction.date >= first_day_of_month,
                   Transaction.date <= today).scalar() or 0

        month_expense = db.session.query(db.func.sum(Transaction.expense)).\
            filter(Transaction.date >= first_day_of_month,
                   Transaction.date <= today).scalar() or 0

        # Get recent transactions (last 10)
        recent_transactions = Transaction.query.\
            order_by(Transaction.date.desc(), Transaction.id.desc()).limit(10).all()

        # Build account name map for display
        account_map = {a.id: a.account_name for a in accounts}

        return render_template('dashboard.html',
                               accounts=account_data,
                               total_balance=total_balance,
                               month_income=month_income,
                               month_expense=month_expense,
                               recent_transactions=recent_transactions,
                               account_map=account_map)

    # ==================== Account Management Routes ====================

    @app.route('/accounts', methods=['GET', 'POST'])
    @login_required
    def accounts():
        """Account management - list and add accounts."""
        if request.method == 'POST':
            account_name = request.form.get('account_name', '').strip()
            initial_balance_str = request.form.get('initial_balance', '0')

            if not account_name:
                flash('账户名称不能为空。', 'danger')
                return redirect(url_for('accounts'))

            # Check if account name already exists
            if Account.query.filter_by(account_name=account_name).first():
                flash(f'账户 "{account_name}" 已存在。', 'danger')
                return redirect(url_for('accounts'))

            try:
                initial_balance = float(initial_balance_str) if initial_balance_str else 0.0
            except ValueError:
                flash('期初余额格式错误。', 'danger')
                return redirect(url_for('accounts'))

            new_account = Account(
                account_name=account_name,
                initial_balance=initial_balance,
                created_by=current_user.id
            )
            db.session.add(new_account)
            db.session.commit()

            flash(f'账户 "{account_name}" 创建成功。', 'success')
            return redirect(url_for('accounts'))

        # GET request - list all accounts
        all_accounts = Account.query.all()
        account_data = []

        for account in all_accounts:
            # Count transactions for this account
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

    @app.route('/account/<int:account_id>/rename', methods=['POST'])
    @login_required
    def rename_account(account_id):
        """Rename an account."""
        account = Account.query.get_or_404(account_id)
        new_name = request.form.get('new_name', '').strip()

        if not new_name:
            flash('账户名称不能为空。', 'danger')
            return redirect(url_for('accounts'))

        # Check if new name already exists (and is not this account)
        existing = Account.query.filter_by(account_name=new_name).first()
        if existing and existing.id != account_id:
            flash(f'账户名称 "{new_name}" 已被使用。', 'danger')
            return redirect(url_for('accounts'))

        old_name = account.account_name
        account.account_name = new_name
        db.session.commit()

        flash(f'账户已从 "{old_name}" 重命名为 "{new_name}"。', 'success')
        return redirect(url_for('accounts'))

    @app.route('/account/<int:account_id>/delete', methods=['POST'])
    @login_required
    def delete_account(account_id):
        """Delete an account and all its transactions."""
        account = Account.query.get_or_404(account_id)

        # Check if account has transactions
        transaction_count = Transaction.query.filter_by(account_id=account_id).count()
        if transaction_count > 0:
            flash(f'无法删除账户 "{account.account_name}"，该账户下还有 {transaction_count} 条流水记录。请先删除所有流水记录。', 'danger')
            return redirect(url_for('accounts'))

        account_name = account.account_name
        db.session.delete(account)
        db.session.commit()

        flash(f'账户 "{account_name}" 已删除。', 'success')
        return redirect(url_for('accounts'))

    # ==================== Transaction Routes ====================

    @app.route('/transaction/add', methods=['GET', 'POST'])
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

            # Validation
            if not date_str or not account_id:
                flash('日期和账户为必填项。', 'danger')
                return redirect(url_for('add_transaction'))

            try:
                trans_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('日期格式错误，请使用 YYYY-MM-DD 格式。', 'danger')
                return redirect(url_for('add_transaction'))

            try:
                income = float(income_str) if income_str else 0.0
                expense = float(expense_str) if expense_str else 0.0
            except ValueError:
                flash('收入或支出金额格式错误。', 'danger')
                return redirect(url_for('add_transaction'))

            if income < 0 or expense < 0:
                flash('收入和支出不能为负数。', 'danger')
                return redirect(url_for('add_transaction'))

            if income == 0 and expense == 0:
                flash('收入和支出不能同时为0。', 'danger')
                return redirect(url_for('add_transaction'))

            # Verify account exists
            account = Account.query.get(account_id)
            if not account:
                flash('所选账户不存在。', 'danger')
                return redirect(url_for('add_transaction'))

            # Calculate balance_after
            balance_before = Transaction.get_balance_before_transaction(account_id, trans_date)
            balance_after = balance_before + income - expense

            # Create transaction
            transaction = Transaction(
                date=trans_date,
                account_id=account_id,
                summary=summary,
                income=income,
                expense=expense,
                balance_after=balance_after,
                note1=note1,
                note2=note2,
                created_by=current_user.id
            )
            db.session.add(transaction)
            db.session.commit()

            # Recalculate balances for subsequent transactions
            Transaction.recalculate_balances(account_id, trans_date)

            flash('流水记录添加成功。', 'success')
            return redirect(url_for('add_transaction'))

        # GET request - show form
        accounts = Account.query.order_by(Account.account_name).all()
        today = date.today().strftime('%Y-%m-%d')
        return render_template('transaction_add.html', accounts=accounts, today=today)

    @app.route('/transactions')
    @login_required
    def list_transactions():
        """List transactions with filters."""
        # Get filter parameters
        start_date_str = request.args.get('start_date', '')
        end_date_str = request.args.get('end_date', '')
        account_id = request.args.get('account_id', '')
        keyword = request.args.get('keyword', '').strip()

        # Build query
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
                    Transaction.note2.contains(keyword)
                )
            )

        # Order by date descending, then by id descending
        query = query.order_by(Transaction.date.desc(), Transaction.id.desc())

        # Calculate totals for the filtered results (before pagination)
        total_income = db.session.query(db.func.sum(Transaction.income))
        total_expense = db.session.query(db.func.sum(Transaction.expense))

        # Apply same filters to total queries
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                total_income = total_income.filter(Transaction.date >= start_date)
                total_expense = total_expense.filter(Transaction.date >= start_date)
            except ValueError:
                pass

        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                total_income = total_income.filter(Transaction.date <= end_date)
                total_expense = total_expense.filter(Transaction.date <= end_date)
            except ValueError:
                pass

        if account_id:
            total_income = total_income.filter(Transaction.account_id == account_id)
            total_expense = total_expense.filter(Transaction.account_id == account_id)

        if keyword:
            filter_condition = db.or_(
                Transaction.summary.contains(keyword),
                Transaction.note1.contains(keyword),
                Transaction.note2.contains(keyword)
            )
            total_income = total_income.filter(filter_condition)
            total_expense = total_expense.filter(filter_condition)

        total_income = total_income.scalar() or 0
        total_expense = total_expense.scalar() or 0

        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = app.config.get('ITEMS_PER_PAGE', 50)
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        transactions = pagination.items

        # Get all accounts for filter dropdown
        accounts = Account.query.order_by(Account.account_name).all()
        account_map = {a.id: a.account_name for a in accounts}

        return render_template('transaction_list.html',
                               transactions=transactions,
                               pagination=pagination,
                               accounts=accounts,
                               account_map=account_map,
                               total_income=total_income,
                               total_expense=total_expense,
                               start_date=start_date_str,
                               end_date=end_date_str,
                               selected_account=account_id,
                               keyword=keyword)

    @app.route('/transaction/edit/<int:transaction_id>', methods=['GET', 'POST'])
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

            # Validation
            if not date_str or not account_id:
                flash('日期和账户为必填项。', 'danger')
                return redirect(url_for('edit_transaction', transaction_id=transaction_id))

            try:
                trans_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('日期格式错误，请使用 YYYY-MM-DD 格式。', 'danger')
                return redirect(url_for('edit_transaction', transaction_id=transaction_id))

            try:
                income = float(income_str) if income_str else 0.0
                expense = float(expense_str) if expense_str else 0.0
            except ValueError:
                flash('收入或支出金额格式错误。', 'danger')
                return redirect(url_for('edit_transaction', transaction_id=transaction_id))

            if income < 0 or expense < 0:
                flash('收入和支出不能为负数。', 'danger')
                return redirect(url_for('edit_transaction', transaction_id=transaction_id))

            if income == 0 and expense == 0:
                flash('收入和支出不能同时为0。', 'danger')
                return redirect(url_for('edit_transaction', transaction_id=transaction_id))

            # Verify account exists
            account = Account.query.get(account_id)
            if not account:
                flash('所选账户不存在。', 'danger')
                return redirect(url_for('edit_transaction', transaction_id=transaction_id))

            # Update transaction
            transaction.date = trans_date
            transaction.account_id = account_id
            transaction.summary = summary
            transaction.income = income
            transaction.expense = expense
            transaction.note1 = note1
            transaction.note2 = note2
            transaction.updated_at = datetime.utcnow()

            db.session.commit()

            # Recalculate balances
            # If account changed, need to recalculate both old and new account
            if old_account_id != int(account_id):
                # Recalculate old account from old date
                Transaction.recalculate_balances(old_account_id, old_date)
                # Recalculate new account from new date
                Transaction.recalculate_balances(int(account_id), trans_date)
            else:
                # Same account, recalculate from earlier of old and new date
                recalc_from = min(old_date, trans_date)
                Transaction.recalculate_balances(int(account_id), recalc_from)

            flash('流水记录更新成功。', 'success')
            return redirect(url_for('list_transactions'))

        # GET request - show edit form
        accounts = Account.query.order_by(Account.account_name).all()
        return render_template('transaction_edit.html',
                               transaction=transaction,
                               accounts=accounts)

    @app.route('/transaction/delete/<int:transaction_id>', methods=['POST'])
    @login_required
    def delete_transaction(transaction_id):
        """Delete a transaction."""
        transaction = Transaction.query.get_or_404(transaction_id)
        account_id = transaction.account_id
        trans_date = transaction.date

        db.session.delete(transaction)
        db.session.commit()

        # Recalculate balances for subsequent transactions
        Transaction.recalculate_balances(account_id, trans_date)

        flash('流水记录已删除。', 'success')
        return redirect(url_for('list_transactions'))

    # ==================== Excel Import/Export Routes ====================

    @app.route('/transactions/export')
    @login_required
    def export_transactions():
        """Export transactions to Excel."""
        # Get filter parameters (same as list_transactions)
        start_date_str = request.args.get('start_date', '')
        end_date_str = request.args.get('end_date', '')
        account_id = request.args.get('account_id', '')
        keyword = request.args.get('keyword', '').strip()

        # Build query (same as list_transactions)
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
                    Transaction.note2.contains(keyword)
                )
            )

        # Order by date ascending for export
        query = query.order_by(Transaction.date, Transaction.id)
        transactions = query.all()

        # Get account map
        accounts = Account.query.all()
        account_map = {a.id: a.account_name for a in accounts}

        # Generate Excel
        output = export_transactions_to_excel(transactions, account_map)

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"transactions_{timestamp}.xlsx"

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

    @app.route('/transactions/import', methods=['GET', 'POST'])
    @login_required
    def import_transactions():
        """Import transactions from Excel."""
        if request.method == 'POST':
            if 'file' not in request.files:
                flash('请选择要上传的文件。', 'danger')
                return redirect(url_for('import_transactions'))

            file = request.files['file']
            if file.filename == '':
                flash('请选择要上传的文件。', 'danger')
                return redirect(url_for('import_transactions'))

            if not file.filename.endswith(('.xlsx', '.xls')):
                flash('请上传 Excel 文件 (.xlsx 或 .xls)。', 'danger')
                return redirect(url_for('import_transactions'))

            # Get account name to ID mapping
            accounts = Account.query.all()
            account_name_to_id = {a.account_name: a.id for a in accounts}

            if not accounts:
                flash('系统中没有账户，请先创建至少一个账户。', 'danger')
                return redirect(url_for('import_transactions'))

            # Parse Excel
            success, result = parse_excel_import(file, account_name_to_id)

            if not success:
                # result contains error messages
                for error in result:
                    flash(error, 'danger')
                return redirect(url_for('import_transactions'))

            # result contains transaction data
            transactions_data = result
            imported_count = 0

            try:
                for data in transactions_data:
                    # Calculate balance_after
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
                        note1=data['note1'],
                        note2=data['note2'],
                        created_by=current_user.id
                    )
                    db.session.add(transaction)
                    imported_count += 1

                db.session.commit()

                # Recalculate all balances
                for account_id in set(t['account_id'] for t in transactions_data):
                    Transaction.recalculate_balances(account_id)

                flash(f'成功导入 {imported_count} 条流水记录。', 'success')
                return redirect(url_for('list_transactions'))

            except Exception as e:
                db.session.rollback()
                flash(f'导入过程中出错：{str(e)}', 'danger')
                return redirect(url_for('import_transactions'))

        # GET request - show import form
        return render_template('transaction_import.html')

    @app.route('/transactions/import/template')
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


def register_cli_commands(app):
    """Register Flask CLI commands."""

    @app.cli.command('create-admin')
    @click.option('--username', prompt=True, help='管理员用户名')
    @click.password_option('--password', help='管理员密码')
    def create_admin(username, password):
        """Create an admin user."""
        if User.query.filter_by(username=username).first():
            click.echo(f'Error: User "{username}" already exists.')
            return

        user = User(username=username, is_admin=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f'Admin user "{username}" created successfully.')

    @app.cli.command('create-user')
    @click.option('--username', prompt=True, help='用户名')
    @click.password_option('--password', help='密码')
    @click.option('--admin', is_flag=True, help='设为管理员')
    def create_user(username, password, admin):
        """Create a new user."""
        if User.query.filter_by(username=username).first():
            click.echo(f'Error: User "{username}" already exists.')
            return

        user = User(username=username, is_admin=admin)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f'User "{username}" created successfully.')

    @app.cli.command('list-users')
    def list_users():
        """List all users."""
        users = User.query.all()
        if not users:
            click.echo('No users found.')
            return

        click.echo(f'{"ID":<5}{"Username":<20}{"Admin":<10}{"Created":<20}')
        click.echo('-' * 55)
        for user in users:
            click.echo(f'{user.id:<5}{user.username:<20}{"Yes" if user.is_admin else "No":<10}{user.created_at.strftime("%Y-%m-%d %H:%M"):<20}')


# Create the application instance
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
