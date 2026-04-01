from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """User model for authentication."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    accounts = db.relationship('Account', backref='creator', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='creator', lazy='dynamic')

    def set_password(self, password):
        """Hash and set user password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if provided password matches hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class Account(db.Model):
    """Account model for managing financial accounts."""
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    account_name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    initial_balance = db.Column(db.Float, default=0.0)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    transactions = db.relationship('Transaction', backref='account', lazy='dynamic',
                                    cascade='all, delete-orphan')

    def get_current_balance(self):
        """Calculate current balance based on initial balance and all transactions."""
        total_income = db.session.query(db.func.sum(Transaction.income)).\
            filter(Transaction.account_id == self.id).scalar() or 0
        total_expense = db.session.query(db.func.sum(Transaction.expense)).\
            filter(Transaction.account_id == self.id).scalar() or 0
        return self.initial_balance + total_income - total_expense

    def __repr__(self):
        return f'<Account {self.account_name}>'


class Transaction(db.Model):
    """Transaction model for recording financial transactions."""
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False, index=True)
    summary = db.Column(db.String(200))
    income = db.Column(db.Float, default=0.0)
    expense = db.Column(db.Float, default=0.0)
    balance_after = db.Column(db.Float, default=0.0)
    note1 = db.Column(db.String(200))
    note2 = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Transaction {self.id} {self.date}>'

    @staticmethod
    def recalculate_balances(account_id, from_date=None):
        """Recalculate balance_after for all transactions in an account.

        This should be called after editing or deleting a transaction.
        """
        # Get the account
        account = Account.query.get(account_id)
        if not account:
            return

        # Build query for transactions
        query = Transaction.query.filter(Transaction.account_id == account_id)
        if from_date:
            query = query.filter(Transaction.date >= from_date)

        # Get transactions ordered by date, then by id for stable ordering
        transactions = query.order_by(Transaction.date, Transaction.id).all()

        # Calculate starting balance
        if from_date:
            # Get balance before from_date
            prior_income = db.session.query(db.func.sum(Transaction.income)).\
                filter(Transaction.account_id == account_id,
                       Transaction.date < from_date).scalar() or 0
            prior_expense = db.session.query(db.func.sum(Transaction.expense)).\
                filter(Transaction.account_id == account_id,
                       Transaction.date < from_date).scalar() or 0
            current_balance = account.initial_balance + prior_income - prior_expense
        else:
            current_balance = account.initial_balance

        # Update each transaction's balance_after
        for trans in transactions:
            current_balance = current_balance + trans.income - trans.expense
            trans.balance_after = current_balance

        db.session.commit()

    @staticmethod
    def get_balance_before_transaction(account_id, date, exclude_id=None):
        """Get the balance before a specific date for an account."""
        account = Account.query.get(account_id)
        if not account:
            return 0

        query = db.session.query(db.func.sum(Transaction.income - Transaction.expense)).\
            filter(Transaction.account_id == account_id,
                   Transaction.date < date)

        if exclude_id:
            query = query.filter(Transaction.id != exclude_id)

        prior_balance = query.scalar() or 0
        return account.initial_balance + prior_balance
