from models import db, User


def _text(response):
    return response.data.decode('utf-8')


def test_login_success(client, admin_user):
    response = client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert '首页概览' in _text(response) or 'dashboard' in _text(response).lower()


def test_login_failure(client):
    response = client.post('/login', data={
        'username': 'nobody',
        'password': 'wrong'
    }, follow_redirects=True)
    assert '用户名或密码错误' in _text(response)


def test_logout(client, admin_user):
    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    })
    response = client.get('/logout', follow_redirects=True)
    assert '您已成功退出登录' in _text(response)


def test_change_password(client, admin_user):
    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    })
    response = client.post('/change-password', data={
        'old_password': 'admin123',
        'new_password': 'newpass123',
        'confirm_password': 'newpass123'
    }, follow_redirects=True)
    assert '密码修改成功' in _text(response)

    client.get('/logout', follow_redirects=True)
    response = client.post('/login', data={
        'username': 'admin',
        'password': 'newpass123'
    }, follow_redirects=True)
    assert response.status_code == 200


def test_admin_required_blocks_regular_user(client, regular_user):
    client.post('/login', data={
        'username': 'user',
        'password': 'user123'
    })
    response = client.get('/note-options', follow_redirects=True)
    assert '需要管理员权限' in _text(response)


def test_admin_required_allows_admin(client, admin_user):
    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    })
    response = client.get('/note-options', follow_redirects=True)
    assert response.status_code == 200
    assert '需要管理员权限' not in _text(response)


def test_user_management_crud(client, admin_user, app):
    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    })

    response = client.post('/users/add', data={
        'username': 'tester',
        'password': 'testpass',
        'is_admin': 'on'
    }, follow_redirects=True)
    assert 'tester' in _text(response)

    with app.app_context():
        user = User.query.filter_by(username='tester').first()
        assert user is not None
        user_id = user.id

    response = client.post(f'/users/{user_id}/edit', data={
        'is_admin': ''
    }, follow_redirects=True)
    assert '已更新' in _text(response)

    with app.app_context():
        user = User.query.get(user_id)
        assert user.is_admin is False

    response = client.post(f'/users/{user_id}/reset-password', data={
        'new_password': 'reset123'
    }, follow_redirects=True)
    assert '密码已重置' in _text(response)

    response = client.post(f'/users/{user_id}/delete', data={}, follow_redirects=True)
    assert '已删除' in _text(response)

    with app.app_context():
        assert User.query.get(user_id) is None
