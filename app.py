import os
import click
from datetime import datetime
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate

from config import config
from models import db, User
from routes import auth_bp, main_bp, accounts_bp, transactions_bp, reports_bp, settings_bp


def create_app(config_name=None):
    """Application factory pattern."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

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

    # Add context processor to provide current datetime to all templates
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)

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
