"""Core AI analyzer: intent recognition, SQL template execution, chart data building."""

import json
import re
from datetime import date, timedelta
from flask import current_app
from sqlalchemy import func, extract

from models import db, Transaction, AiChatSession, AiChatMessage
from utils.ai_provider import get_ai_provider
from utils.reporting import get_last_6_months_trends

# Intent type descriptions for LLM prompt
INTENT_DESCRIPTIONS = {
    'project_income': '各项目收入/支出汇总（按 note1 分组）',
    'expense_structure': '支出结构分析（按 note2/note3 分类占比）',
    'trend': '收入/支出趋势分析（月度时间序列）',
    'profit_loss': '盈亏概况（总收入、总支出、净额）',
    'general': '一般性问题，不属于上述类型',
}

# System prompt for intent recognition
INTENT_SYSTEM_PROMPT = """你是一个财务数据分析助手。用户会提出一个关于财务数据的问题，你需要识别用户的意图并返回 JSON 格式的结果。

可用的意图类型：
""" + json.dumps(INTENT_DESCRIPTIONS, ensure_ascii=False, indent=2) + """

返回格式（纯 JSON，不要添加其他文字）：
{
    "intent_type": "上述类型之一",
    "parameters": {
        "start_date": "YYYY-MM-DD 或 null",
        "end_date": "YYYY-MM-DD 或 null",
        "extra_info": "其他需要提取的信息，如项目名称等，或 null"
    }
}

日期支持："本月"、"上月"、"近6个月"、"近3个月"、"今年"、"2024年3月"、"2024-01-01至2024-03-31" 等表达。
如果用户的问题不涉及具体日期范围，start_date 和 end_date 设为 null。"""

# Available field descriptions
FIELD_DESCRIPTIONS = """
数据表字段说明：
- date: 交易日期
- summary: 摘要
- income: 收入金额
- expense: 支出金额
- note1: 项目名称（如"项目A-开发"）
- note2: 收入/支出大类
- note3: 明细子类
- note4: 备注4
- note5: 备注5
"""


def parse_date_expression(expr):
    """Parse a date expression string into start_date and end_date.

    Supports: "本月", "上月", "近6个月", "近3个月", "今年", "2024年3月", etc.
    """
    if not expr:
        return None, None

    today = date.today()
    expr = expr.strip()

    # "本月"
    if expr == '本月':
        return date(today.year, today.month, 1), _get_month_end(today.year, today.month)

    # "上月"
    if expr == '上月':
        last_month = today.month - 1 if today.month > 1 else 12
        last_year = today.year if today.month > 1 else today.year - 1
        return date(last_year, last_month, 1), _get_month_end(last_year, last_month)

    # "近N个月"
    match = re.match(r'近(\d+)个月', expr)
    if match:
        n = int(match.group(1))
        end = today
        start = today - timedelta(days=30 * n)
        return start, end

    # "今年"
    if '今年' in expr:
        return date(today.year, 1, 1), date(today.year, 12, 31)

    # "YYYY年M月"
    match = re.match(r'(\d{4})年(\d{1,2})月', expr)
    if match:
        y, m = int(match.group(1)), int(match.group(2))
        return date(y, m, 1), _get_month_end(y, m)

    # "YYYY年"
    match = re.match(r'(\d{4})年$', expr)
    if match:
        y = int(match.group(1))
        return date(y, 1, 1), date(y, 12, 31)

    # "YYYY-MM-DD至YYYY-MM-DD"
    match = re.match(r'(\d{4}-\d{1,2}-\d{1,2})\s*至\s*(\d{4}-\d{1,2}-\d{1,2})', expr)
    if match:
        try:
            s = date.fromisoformat(match.group(1))
            e = date.fromisoformat(match.group(2))
            return s, e
        except ValueError:
            pass

    # "YYYY-MM-DD"
    match = re.match(r'(\d{4}-\d{1,2}-\d{1,2})$', expr)
    if match:
        try:
            d = date.fromisoformat(match.group(1))
            return d, d
        except ValueError:
            pass

    return None, None


def _get_month_end(year, month):
    """Get the last day of a given month."""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def fallback_intent_recognition(query):
    """Keyword-based fallback intent recognition when AI is unavailable."""
    query_lower = query.lower()

    # Project income
    if any(kw in query_lower for kw in ['项目', 'note1']) and any(kw in query_lower for kw in ['收入', '收支', '汇总']):
        return 'project_income', {}

    # Expense structure
    if any(kw in query_lower for kw in ['支出结构', '支出占比', '支出分类', '支出分布', '支出构成']):
        return 'expense_structure', {}

    # Trend
    if any(kw in query_lower for kw in ['趋势', 'trend', '近', '个月收入']):
        return 'trend', {}

    # Profit/loss
    if any(kw in query_lower for kw in ['盈亏', '利润', 'profit', '净额', '概况']):
        return 'profit_loss', {}

    # Default: general
    return 'general', {}


def analyze_intent(query, session_id=None):
    """Analyze user query to determine intent and parameters.

    Steps:
    1. Try LLM-based intent recognition
    2. Fall back to keyword matching if AI is unavailable
    3. Parse dates from the parameters
    4. Execute the appropriate SQL template query
    5. Build chart data and generate reply text

    Returns:
        dict with keys: intent_type, parameters, chart_type, chart_data, reply_text
    """
    provider = get_ai_provider()
    intent_type = None
    parameters = {}

    # Step 1: Try LLM intent recognition
    if provider:
        messages = [{'role': 'user', 'content': query + '\n\n' + FIELD_DESCRIPTIONS}]
        response = provider.chat(messages, max_tokens=512, system=INTENT_SYSTEM_PROMPT)
        parsed = provider.parse_json_response(response) if response else None
        if parsed and 'intent_type' in parsed:
            intent_type = parsed['intent_type']
            parameters = parsed.get('parameters', {}) or {}

    # Step 2: Fallback
    if not intent_type:
        intent_type, parameters = fallback_intent_recognition(query)

    # Step 3: Parse dates
    start_date = None
    end_date = None

    # Check if LLM returned date strings
    raw_start = parameters.get('start_date') if isinstance(parameters, dict) else None
    raw_end = parameters.get('end_date') if isinstance(parameters, dict) else None

    if raw_start:
        start_date, _ = parse_date_expression(raw_start)
    if raw_end:
        _, end_date = parse_date_expression(raw_end)

    # If no dates were extracted, try parsing the full query for common expressions
    if not start_date and not end_date:
        # Try common date expressions from the query itself
        for expr in ['本月', '上月', '今年', '近6个月', '近3个月']:
            if expr in query:
                start_date, end_date = parse_date_expression(expr)
                break

    # Default to "本月" for specific query types if no date specified
    if not start_date and not end_date and intent_type in ('project_income', 'expense_structure', 'profit_loss'):
        start_date, end_date = parse_date_expression('本月')

    # Step 4: Execute SQL template query
    chart_type, chart_data = execute_query(intent_type, start_date, end_date)

    # Step 5: Generate reply text
    reply_text = generate_reply(intent_type, chart_data, query)

    return {
        'intent_type': intent_type,
        'parameters': parameters,
        'chart_type': chart_type,
        'chart_data': chart_data,
        'reply_text': reply_text,
    }


def execute_query(intent_type, start_date=None, end_date=None):
    """Execute a pre-defined SQLAlchemy query based on intent type.

    Returns:
        (chart_type, chart_data) where chart_data is a dict compatible with Chart.js
    """
    # Build date filter
    date_filters = []
    if start_date:
        date_filters.append(Transaction.date >= start_date)
    if end_date:
        date_filters.append(Transaction.date <= end_date)

    base_query = db.session.query()
    if date_filters:
        base_query = base_query.filter(*date_filters)

    if intent_type == 'project_income':
        return _query_project_income(base_query)
    elif intent_type == 'expense_structure':
        return _query_expense_structure(base_query)
    elif intent_type == 'trend':
        return _query_trend()
    elif intent_type == 'profit_loss':
        return _query_profit_loss(base_query)
    else:
        return _query_general()


def _query_project_income(query):
    """GROUP BY note1, SUM(income), SUM(expense) → bar chart."""
    results = query.with_entities(
        Transaction.note1,
        func.sum(Transaction.income).label('total_income'),
        func.sum(Transaction.expense).label('total_expense'),
    ).filter(
        Transaction.note1.isnot(None),
        Transaction.note1 != '',
    ).group_by(Transaction.note1).order_by(func.sum(Transaction.income).desc()).all()

    labels = [r[0] for r in results if r[0]]
    incomes = [float(r[1] or 0) for r in results if r[0]]
    expenses = [float(r[2] or 0) for r in results if r[0]]

    chart_data = {
        'labels': labels,
        'datasets': [
            {
                'label': '收入',
                'data': incomes,
                'backgroundColor': 'rgba(16, 185, 129, 0.7)',
                'borderColor': 'rgba(16, 185, 129, 1)',
                'borderWidth': 1,
            },
            {
                'label': '支出',
                'data': expenses,
                'backgroundColor': 'rgba(244, 63, 94, 0.7)',
                'borderColor': 'rgba(244, 63, 94, 1)',
                'borderWidth': 1,
            },
        ],
    }
    return 'bar', chart_data


def _query_expense_structure(query):
    """GROUP BY note2, SUM(expense) → pie chart."""
    results = query.with_entities(
        Transaction.note2,
        func.sum(Transaction.expense).label('total_expense'),
    ).filter(
        Transaction.note2.isnot(None),
        Transaction.note2 != '',
        Transaction.expense > 0,
    ).group_by(Transaction.note2).order_by(func.sum(Transaction.expense).desc()).all()

    labels = [r[0] for r in results if r[0]]
    values = [float(r[1] or 0) for r in results if r[0]]

    colors = [
        'rgba(99, 102, 241, 0.7)', 'rgba(16, 185, 129, 0.7)', 'rgba(245, 158, 11, 0.7)',
        'rgba(244, 63, 94, 0.7)', 'rgba(6, 182, 212, 0.7)', 'rgba(168, 85, 247, 0.7)',
        'rgba(236, 72, 153, 0.7)', 'rgba(34, 197, 94, 0.7)', 'rgba(251, 146, 60, 0.7)',
        'rgba(148, 163, 184, 0.7)',
    ]
    border_colors = [c.replace('0.7', '1') for c in colors]

    chart_data = {
        'labels': labels,
        'datasets': [{
            'data': values,
            'backgroundColor': colors[:len(labels)],
            'borderColor': border_colors[:len(labels)],
            'borderWidth': 1,
        }],
    }
    return 'pie', chart_data


def _query_trend():
    """Monthly aggregation → line chart (reuse get_last_6_months_trends)."""
    trends = get_last_6_months_trends()

    labels = [t['month'] for t in trends]
    incomes = [t['income'] for t in trends]
    expenses = [t['expense'] for t in trends]

    chart_data = {
        'labels': labels,
        'datasets': [
            {
                'label': '收入',
                'data': incomes,
                'borderColor': 'rgba(16, 185, 129, 1)',
                'backgroundColor': 'rgba(16, 185, 129, 0.1)',
                'tension': 0.3,
                'fill': True,
            },
            {
                'label': '支出',
                'data': expenses,
                'borderColor': 'rgba(244, 63, 94, 1)',
                'backgroundColor': 'rgba(244, 63, 94, 0.1)',
                'tension': 0.3,
                'fill': True,
            },
        ],
    }
    return 'line', chart_data


def _query_profit_loss(query):
    """SUM(income), SUM(expense), net → table."""
    result = query.with_entities(
        func.sum(Transaction.income).label('total_income'),
        func.sum(Transaction.expense).label('total_expense'),
    ).first()

    total_income = float(result[0] or 0)
    total_expense = float(result[1] or 0)
    net = total_income - total_expense

    chart_data = {
        'table': [
            {'item': '总收入', 'value': total_income},
            {'item': '总支出', 'value': total_expense},
            {'item': '净额', 'value': net},
        ],
    }
    return 'table', chart_data


def _query_general():
    """Return no chart for general questions."""
    return None, {}


def generate_reply(intent_type, chart_data, query):
    """Generate a text reply based on intent type and query results.

    If AI provider is available, use LLM to generate natural language response.
    Otherwise, use template-based responses.
    """
    provider = get_ai_provider()

    if provider and chart_data:
        # Use LLM to generate a natural language summary
        data_summary = json.dumps(chart_data, ensure_ascii=False)
        system_prompt = f"""你是一个财务数据分析助手。根据以下查询结果，用简洁的中文生成一段数据分析报告。

查询类型: {intent_type}
用户问题: {query}

数据:
{data_summary}

要求:
1. 用简洁流畅的中文描述
2. 突出关键数据（最高/最低、对比关系）
3. 控制在3-5句话
4. 数字用千位分隔符格式化"""

        response = provider.chat(
            [{'role': 'user', 'content': '请根据数据生成分析解读'}],
            max_tokens=512,
            system=system_prompt,
        )
        if response:
            return response

    # Template-based fallback
    return _template_reply(intent_type, chart_data)


def _template_reply(intent_type, chart_data):
    """Generate reply using predefined templates."""
    if intent_type == 'project_income':
        labels = chart_data.get('labels', [])
        incomes = chart_data.get('datasets', [{}])[0].get('data', [])
        if not labels:
            return '当前日期范围内没有项目数据。'

        lines = [f'共统计到 {len(labels)} 个项目：']
        for label, inc in zip(labels, incomes):
            lines.append(f'  - {label}: 收入 ¥{inc:,.2f}')
        return '\n'.join(lines)

    elif intent_type == 'expense_structure':
        labels = chart_data.get('labels', [])
        values = chart_data.get('datasets', [{}])[0].get('data', [])
        if not labels:
            return '当前日期范围内没有支出数据。'

        total = sum(values)
        lines = [f'支出结构分析（总计 ¥{total:,.2f}）：']
        for label, val in zip(labels, values):
            pct = (val / total * 100) if total > 0 else 0
            lines.append(f'  - {label}: ¥{val:,.2f} ({pct:.1f}%)')
        return '\n'.join(lines)

    elif intent_type == 'trend':
        trends = chart_data.get('labels', [])
        incomes = chart_data.get('datasets', [{}])[0].get('data', [])
        expenses = chart_data.get('datasets', [{}])[1].get('data', [])
        if not trends:
            return '没有可用的趋势数据。'

        lines = ['近6个月收支趋势：']
        for month, inc, exp in zip(trends, incomes, expenses):
            net = inc - exp
            arrow = '↑' if net >= 0 else '↓'
            lines.append(f'  - {month}: 收入 ¥{inc:,.2f}, 支出 ¥{exp:,.2f}, 净额 {arrow}¥{abs(net):,.2f}')
        return '\n'.join(lines)

    elif intent_type == 'profit_loss':
        table = chart_data.get('table', [])
        if not table:
            return '当前日期范围内没有数据。'

        lines = ['盈亏概况：']
        for row in table:
            lines.append(f'  - {row["item"]}: ¥{row["value"]:,.2f}')
        return '\n'.join(lines)

    else:
        return '我目前主要支持以下分析类型：\n1. 各项目收入汇总\n2. 支出结构分析\n3. 近6个月趋势\n4. 盈亏概况\n请尝试提问相关问题。'


def save_message(session_id, role, content, intent_type=None, chart_type=None, chart_data=None):
    """Save a chat message to the database.

    Returns:
        The created AiChatMessage instance.
    """
    chart_data_json = json.dumps(chart_data, ensure_ascii=False) if chart_data else None
    msg = AiChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        intent_type=intent_type,
        chart_type=chart_type,
        chart_data_json=chart_data_json,
    )
    db.session.add(msg)

    # Update session's updated_at
    session = AiChatSession.query.get(session_id)
    if session:
        from datetime import datetime
        session.updated_at = datetime.utcnow()

    db.session.commit()
    return msg
