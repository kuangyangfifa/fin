from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, User, NoteOption, Note1Option
from utils.decorators import admin_required

settings_bp = Blueprint('settings', __name__)


# ==================== Note Options Management Routes ====================

@settings_bp.route('/note-options')
@login_required
@admin_required
def note_options():
    """Note options management page."""
    options_by_field = {}
    for field in ['note2', 'note3', 'note4', 'note5']:
        options_by_field[field] = NoteOption.query.filter_by(
            note_field=field
        ).order_by(NoteOption.sort_order, NoteOption.option_value).all()

    note1_parents = Note1Option.get_all_parents()
    note1_options = {}
    for parent in note1_parents:
        children = Note1Option.get_children_by_parent(parent)
        note1_options[parent] = children

    return render_template('note_options.html',
                           options_by_field=options_by_field,
                           note1_options=note1_options)


@settings_bp.route('/note-options/add', methods=['POST'])
@login_required
@admin_required
def add_note_option():
    """Add a new note option for note2-5."""
    note_field = request.form.get('note_field', '').strip()
    option_value = request.form.get('option_value', '').strip()
    sort_order_str = request.form.get('sort_order', '0')

    if not note_field or not option_value:
        flash('字段和选项值不能为空。', 'danger')
        return redirect(url_for('settings.note_options'))

    if note_field not in ['note2', 'note3', 'note4', 'note5']:
        flash('无效的备注字段。', 'danger')
        return redirect(url_for('settings.note_options'))

    try:
        sort_order = int(sort_order_str) if sort_order_str else 0
    except ValueError:
        sort_order = 0

    existing = NoteOption.query.filter_by(
        note_field=note_field,
        option_value=option_value
    ).first()

    if existing:
        flash(f'选项 "{option_value}" 在 {note_field} 中已存在。', 'danger')
        return redirect(url_for('settings.note_options'))

    option = NoteOption(
        note_field=note_field,
        option_value=option_value,
        sort_order=sort_order,
        created_by=current_user.id
    )
    db.session.add(option)
    db.session.commit()

    flash(f'选项 "{option_value}" 添加成功。', 'success')
    return redirect(url_for('settings.note_options'))


@settings_bp.route('/note-options/<int:option_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_note_option(option_id):
    """Edit a note option."""
    option = NoteOption.query.get_or_404(option_id)
    new_value = request.form.get('option_value', '').strip()
    sort_order_str = request.form.get('sort_order', '0')
    is_active = request.form.get('is_active') == 'on'

    if not new_value:
        flash('选项值不能为空。', 'danger')
        return redirect(url_for('settings.note_options'))

    try:
        sort_order = int(sort_order_str) if sort_order_str else 0
    except ValueError:
        sort_order = 0

    existing = NoteOption.query.filter_by(
        note_field=option.note_field,
        option_value=new_value
    ).first()

    if existing and existing.id != option_id:
        flash(f'选项 "{new_value}" 已存在。', 'danger')
        return redirect(url_for('settings.note_options'))

    option.option_value = new_value
    option.sort_order = sort_order
    option.is_active = is_active
    db.session.commit()

    flash('选项更新成功。', 'success')
    return redirect(url_for('settings.note_options'))


@settings_bp.route('/note-options/<int:option_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_note_option(option_id):
    """Delete a note option."""
    option = NoteOption.query.get_or_404(option_id)
    db.session.delete(option)
    db.session.commit()

    flash(f'选项 "{option.option_value}" 已删除。', 'success')
    return redirect(url_for('settings.note_options'))


# ==================== Note1 (Two-level) Options Routes ====================

@settings_bp.route('/note1-options/add', methods=['POST'])
@login_required
@admin_required
def add_note1_option():
    """Add a new note1 option (two-level hierarchy)."""
    parent_value = request.form.get('parent_value', '').strip()
    child_value = request.form.get('child_value', '').strip()
    sort_order_str = request.form.get('sort_order', '0')

    if not parent_value or not child_value:
        flash('一级选项和二级选项都不能为空。', 'danger')
        return redirect(url_for('settings.note_options'))

    try:
        sort_order = int(sort_order_str) if sort_order_str else 0
    except ValueError:
        sort_order = 0

    existing = Note1Option.query.filter_by(
        parent_value=parent_value,
        child_value=child_value
    ).first()

    if existing:
        flash(f'选项 "{parent_value}-{child_value}" 已存在。', 'danger')
        return redirect(url_for('settings.note_options'))

    option = Note1Option(
        parent_value=parent_value,
        child_value=child_value,
        sort_order=sort_order,
        created_by=current_user.id
    )
    db.session.add(option)
    db.session.commit()

    flash(f'选项 "{parent_value}-{child_value}" 添加成功。', 'success')
    return redirect(url_for('settings.note_options'))


@settings_bp.route('/note1-options/<int:option_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_note1_option(option_id):
    """Edit a note1 option."""
    option = Note1Option.query.get_or_404(option_id)
    parent_value = request.form.get('parent_value', '').strip()
    child_value = request.form.get('child_value', '').strip()
    sort_order_str = request.form.get('sort_order', '0')
    is_active = request.form.get('is_active') == 'on'

    if not parent_value or not child_value:
        flash('一级选项和二级选项都不能为空。', 'danger')
        return redirect(url_for('settings.note_options'))

    try:
        sort_order = int(sort_order_str) if sort_order_str else 0
    except ValueError:
        sort_order = 0

    existing = Note1Option.query.filter_by(
        parent_value=parent_value,
        child_value=child_value
    ).first()

    if existing and existing.id != option_id:
        flash(f'选项 "{parent_value}-{child_value}" 已存在。', 'danger')
        return redirect(url_for('settings.note_options'))

    option.parent_value = parent_value
    option.child_value = child_value
    option.sort_order = sort_order
    option.is_active = is_active
    db.session.commit()

    flash('选项更新成功。', 'success')
    return redirect(url_for('settings.note_options'))


@settings_bp.route('/note1-options/<int:option_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_note1_option(option_id):
    """Delete a note1 option."""
    option = Note1Option.query.get_or_404(option_id)
    db.session.delete(option)
    db.session.commit()

    flash(f'选项 "{option.parent_value}-{option.child_value}" 已删除。', 'success')
    return redirect(url_for('settings.note_options'))


# ==================== User Management Routes ====================

@settings_bp.route('/users')
@login_required
@admin_required
def users():
    """User management page."""
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users.html', users=all_users)


@settings_bp.route('/users/add', methods=['POST'])
@login_required
@admin_required
def add_user():
    """Add a new user via web UI."""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    is_admin = request.form.get('is_admin') == 'on'

    if not username or not password:
        flash('用户名和密码不能为空。', 'danger')
        return redirect(url_for('settings.users'))

    if User.query.filter_by(username=username).first():
        flash(f'用户 "{username}" 已存在。', 'danger')
        return redirect(url_for('settings.users'))

    if len(password) < 6:
        flash('密码长度不能少于6位。', 'danger')
        return redirect(url_for('settings.users'))

    user = User(username=username, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    flash(f'用户 "{username}" 创建成功。', 'success')
    return redirect(url_for('settings.users'))


@settings_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Edit user admin status and active state."""
    user = User.query.get_or_404(user_id)
    is_admin = request.form.get('is_admin') == 'on'

    user.is_admin = is_admin
    db.session.commit()

    flash(f'用户 "{user.username}" 已更新。', 'success')
    return redirect(url_for('settings.users'))


@settings_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Delete a user."""
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('不能删除当前登录的用户。', 'danger')
        return redirect(url_for('settings.users'))

    username = user.username
    db.session.delete(user)
    db.session.commit()

    flash(f'用户 "{username}" 已删除。', 'success')
    return redirect(url_for('settings.users'))


@settings_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    """Reset a user's password by admin."""
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '')

    if not new_password or len(new_password) < 6:
        flash('新密码长度不能少于6位。', 'danger')
        return redirect(url_for('settings.users'))

    user.set_password(new_password)
    db.session.commit()

    flash(f'用户 "{user.username}" 的密码已重置。', 'success')
    return redirect(url_for('settings.users'))
