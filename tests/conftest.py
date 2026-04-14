import pytest
from app import create_app
from models import db, User, Account, Transaction


@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    app = create_app('testing')

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """A test CLI runner for the app."""
    return app.test_cli_runner()


@pytest.fixture
def admin_user(app):
    """Create an admin user."""
    user = User(username='admin', is_admin=True)
    user.set_password('admin123')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def regular_user(app):
    """Create a regular user."""
    user = User(username='user', is_admin=False)
    user.set_password('user123')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def sample_account(app):
    """Create a sample account."""
    account = Account(account_name='Cash', initial_balance=1000)
    db.session.add(account)
    db.session.commit()
    return account
