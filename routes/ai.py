"""AI chat blueprint routes."""

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from models import db, AiChatSession, AiChatMessage
from utils.ai_analyzer import analyze_intent, save_message
from utils.decorators import admin_required

ai_bp = Blueprint('ai', __name__)


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
            import json
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
        session.updated_at = datetime.utcnow()
        db.session.commit()

    response = {
        'reply': result['reply_text'],
        'chart_type': result['chart_type'],
        'chart_data': result['chart_data'],
        'intent_type': result['intent_type'],
    }

    return jsonify(response)
