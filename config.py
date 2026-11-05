import os
from datetime import timedelta


class Config:
    """Base configuration class."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Database configuration - SQLite for development, PostgreSQL for production
    _db_url = os.environ.get('DATABASE_URL') or 'sqlite:///finance_web.db'
    SQLALCHEMY_DATABASE_URI = _db_url
    # SQLite 为整库写锁：多 worker 并发写时给足等待时间，避免 database is locked。
    # 切换 PostgreSQL 后不要传 connect_args。
    if _db_url.startswith('sqlite'):
        SQLALCHEMY_ENGINE_OPTIONS = {'connect_args': {'timeout': 15}}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Upload configuration
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file upload
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')

    # DeepSeek AI configuration
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
    DEEPSEEK_BASE_URL = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    DEEPSEEK_MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')

    AI_PROVIDER = os.environ.get('AI_PROVIDER', '').strip()

    # Qwen AI configuration (OpenAI-compatible)
    QWEN_API_KEY = os.environ.get('QWEN_API_KEY', '')
    QWEN_BASE_URL = os.environ.get('QWEN_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    QWEN_MODEL = os.environ.get('QWEN_MODEL', 'qwen-plus')

    # Claude AI configuration
    CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')
    CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')

    # Application configuration
    ITEMS_PER_PAGE = 50  # Pagination for transaction list

    # 退费审核模块入口（独立 Node 服务，由 Nginx 反代到同域 /refund/）
    # 独立域名部署时改为完整 URL，例如 https://refund.example.com/
    REFUND_URL = os.environ.get('REFUND_URL', '/refund/')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    # In production, ensure SECRET_KEY and DATABASE_URL are set via environment variables


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
