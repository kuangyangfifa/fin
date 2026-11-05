from .auth import auth_bp
from .main import main_bp
from .accounts import accounts_bp
from .transactions import transactions_bp
from .reports import reports_bp
from .settings import settings_bp
from .ai import ai_bp

__all__ = [
    'auth_bp',
    'main_bp',
    'accounts_bp',
    'transactions_bp',
    'reports_bp',
    'settings_bp',
    'ai_bp',
]
