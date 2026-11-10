"""AI chat blueprint routes."""

import json
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user

from models import db, AiChatSession, AiChatMessage
from utils.ai_analyzer import analyze_intent, save_message
from utils.ai_provider import get_ai_provider
from utils.decorators import admin_required

ai_bp = Blueprint('ai', __name__)


def _utcnow():
    """Naive UTC now; matches the timestamp convention used by the models."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


PROVIDER_META = {
    'deepseek': ('DeepSeek', 'DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL', 'DEEPSEEK_BASE_URL'),
    'qwen': ('通义千问', 'QWEN_API_KEY', 'QWEN_MODEL', 'QWEN_BASE_URL'),
    'claude': ('Claude', 'CLAUDE_API_KEY', 'CLAUDE_MODEL', None),
}


def _ai_config_snapshot():
    """Build a key-free description of the current AI configuration."""
    cfg = current_app.config
    name = (cfg.get('AI_PROVIDER') or '').strip().lower()
    meta = PROVIDER_META.get(name)

    if not name:
        return {
            'provider': '', 'provider_label': '未配置', 'model': '',
            'base_url': '', 'api_key_configured': False,
            'state': 'disabled',
            'message': '未设置 AI_PROVIDER，当前仅使用关键词匹配与模板回复',
        }

    label, key_field, model_field, url_field = meta or (name, '', '', None)
    has_key = bool(cfg.get(key_field)) if key_field else False
    info = {
        'provider': name,
        'provider_label': label,
        'model': cfg.get(model_field, '') if model_field else '',
        'base_url': cfg.get(url_field, '') if url_field else '',
        'api_key_configured': has_key,
        'state': 'ready',
        'message': '配置就绪',
    }

    if not meta:
        info.update(state='error', message=f'未知的 AI_PROVIDER：{name}')
    elif not has_key:
        info.update(state='error', message=f'缺少 {key_field}，请在 .env 中补齐后重启服务')
    else:
        try:
            if get_ai_provider() is None:
                info.update(state='error', message='驱动初始化失败，请查看服务日志')
        except Exception as exc:
            info.update(state='error', message=f'驱动初始化异常：{type(exc).__name__}: {exc}')
    return info


@ai_bp.route('/ai/status', methods=['GET'])
@login_required
@admin_required
def ai_status():
    """Report AI configuration status (never returns the API key)."""
    return jsonify(_ai_config_snapshot())


@ai_bp.route('/ai/status/ping', methods=['POST'])
@login_required
@admin_required
def ai_status_ping():
    """Run one tiny real request against the configured model."""
    provider = get_ai_provider()
    if provider is None:
        return jsonify({'ok': False, 'message': '未配置可用的 AI 驱动，请先检查 /ai/status'})

    reply = provider.chat(
        [{'role': 'user', 'content': '只回复两个字：正常'}],
        max_tokens=16,
        system='你是连通性测试助手，按要求原样回复',
    )
    return jsonify({
        'ok': bool(reply),
        'reply': reply or '',
        'message': '模型连通正常' if reply else '模型未返回内容，请查看服务日志',
    })


@ai_bp.route('/ai')
@login_required
@admin_required
def ai_chat():
    """AI chat main page."""
    return render_template('ai_chat.html')


@ai_bp.route('/ai/sessions', methods=['GET'])
@login_required
@admin_required
def list_sessions():
    """List user's chat sessions (JSON)."""
    sessions = AiChatSession.query.filter_by(user_id=current_user.id)\
        .order_by(AiChatSession.updated_at.desc()).all()

    result = []
    for s in sessions:
        result.append({
            'id': s.id,
            'title': s.title,
            'created_at': s.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': s.updated_at.strftime('%Y-%m-%d %H:%M') if s.updated_at else '',
            'message_count': s.messages.count(),
        })
    return jsonify(result)


@ai_bp.route('/ai/sessions', methods=['POST'])
@login_required
@admin_required
def create_session():
    """Create a new chat session."""
    data = request.get_json()
    title = data.get('title', '新对话')

    session = AiChatSession(
        user_id=current_user.id,
        title=title,
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({
        'id': session.id,
        'title': session.title,
        'created_at': session.created_at.strftime('%Y-%m-%d %H:%M'),
        'message_count': 0,
    }), 201


@ai_bp.route('/ai/sessions/<int:session_id>', methods=['GET'])
@login_required
@admin_required
def get_session(session_id):
    """Get a session and its messages."""
    session = AiChatSession.query.filter_by(
        id=session_id, user_id=current_user.id
    ).first_or_404()

    messages = []
    for msg in session.messages.order_by(AiChatMessage.created_at.asc()).all():
        msg_data = {
            'id': msg.id,
            'role': msg.role,
            'content': msg.content,
            'intent_type': msg.intent_type,
            'chart_type': msg.chart_type,
            'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }
        if msg.chart_data_json:
            msg_data['chart_data'] = json.loads(msg.chart_data_json)
        messages.append(msg_data)

    return jsonify({
        'id': session.id,
        'title': session.title,
        'messages': messages,
    })


@ai_bp.route('/ai/sessions/<int:session_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_session(session_id):
    """Delete a chat session and all its messages."""
    session = AiChatSession.query.filter_by(
        id=session_id, user_id=current_user.id
    ).first_or_404()

    db.session.delete(session)
    db.session.commit()

    return jsonify({'status': 'ok'})


@ai_bp.route('/ai/chat/<int:session_id>', methods=['POST'])
@login_required
@admin_required
def send_message(session_id):
    """Send a message and get an AI response."""
    session = AiChatSession.query.filter_by(
        id=session_id, user_id=current_user.id
    ).first_or_404()

    data = request.get_json()
    user_query = data.get('message', '').strip()

    if not user_query:
        return jsonify({'error': '消息不能为空'}), 400

    # Save user message
    save_message(session_id, 'user', user_query)

    # Analyze intent and generate response
    result = analyze_intent(user_query, session_id)

    # Save assistant message
    save_message(
        session_id=session_id,
        role='assistant',
        content=result['reply_text'],
        intent_type=result['intent_type'],
        chart_type=result['chart_type'],
        chart_data=result['chart_data'],
    )

    # Update session title if it's still the default
    if session.title == '新对话':
        # Use first few chars of user query as title
        session.title = user_query[:30] + ('...' if len(user_query) > 30 else '')
        session.updated_at = _utcnow()
        db.session.commit()

    response = {
        'reply': result['reply_text'],
        'chart_type': result['chart_type'],
        'chart_data': result['chart_data'],
        'intent_type': result['intent_type'],
        'date_range_note': result.get('date_range_note'),
    }

    return jsonify(response)
