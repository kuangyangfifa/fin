from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

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
            return redirect(next_page if next_page else url_for('main.index'))
        else:
            flash('用户名或密码错误。', 'danger')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('您已成功退出登录。', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Allow current user to change their password."""
    if request.method == 'POST':
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not old_password or not new_password or not confirm_password:
            flash('请填写所有密码字段。', 'danger')
            return redirect(url_for('auth.change_password'))

        if not current_user.check_password(old_password):
            flash('当前密码不正确。', 'danger')
            return redirect(url_for('auth.change_password'))

        if new_password != confirm_password:
            flash('两次输入的新密码不一致。', 'danger')
            return redirect(url_for('auth.change_password'))

        if len(new_password) < 6:
            flash('新密码长度不能少于6位。', 'danger')
            return redirect(url_for('auth.change_password'))

        current_user.set_password(new_password)
        from models import db
        db.session.commit()
        flash('密码修改成功。', 'success')
        return redirect(url_for('main.index'))

    return render_template('change_password.html')
