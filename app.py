import hashlib
import os
import sqlite3
import click
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

# Load .env file before any config imports
load_dotenv()

from config import config
from models import db, User
from routes import auth_bp, main_bp, accounts_bp, transactions_bp, reports_bp, settings_bp, ai_bp


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """SQLite 开启 WAL 与写锁等待，缓解多 worker 并发写冲突。

    仅对 SQLite 连接生效；切换 PostgreSQL 后本监听器自然空转。
    """
    if isinstance(dbapi_conn, sqlite3.Connection):
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=15000")
        finally:
            cur.close()


def create_app(config_name=None):
    """Application factory pattern."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # 静态资源版本号：以 custom.css 内容为准生成短指纹，模板在静态 URL 后附 ?v=。
    # 服务器 Nginx 对 /static/ 有强缓存，若 URL 不变，改了样式用户仍会看到旧版，
    # 典型症状是新增的尺寸规则不生效、图片按原始尺寸撑破布局。
    css_path = os.path.join(app.static_folder or '', 'css', 'custom.css')
    try:
        with open(css_path, 'rb') as _css:
            app.config['STATIC_VERSION'] = hashlib.md5(_css.read()).hexdigest()[:8]
    except OSError:
        app.config['STATIC_VERSION'] = '0'

    # Nginx 反代后正确识别 https 与客户端 IP，保证 url_for 生成的外链、
    # secure cookie 判断与微信回调地址不出错。信任 1 层代理；
    # 若前面还有阿里云 SLB / CDN，按实际代理层数调大各值。
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Initialize extensions
    db.init_app(app)

    # Initialize Flask-Migrate
    Migrate(app, db)

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录以访问此页面。'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Add context processor to provide shared template variables
    @app.context_processor
    def inject_globals():
        return {
            'now': datetime.now(),
            'refund_url': app.config.get('REFUND_URL', '/refund/'),
            'APP_NAME': app.config.get('APP_NAME', 'LEXUE财务管理系统'),
            'STATIC_VERSION': app.config.get('STATIC_VERSION', '0'),
        }

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(ai_bp)

    # Register CLI commands
    register_cli_commands(app)

    return app


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
