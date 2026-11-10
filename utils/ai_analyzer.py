"""Core AI analyzer: intent recognition, SQL template execution, chart data building."""

import json
import re
from datetime import date, datetime, timedelta, timezone
from flask import current_app
from sqlalchemy import func

from models import db, Transaction, AiChatSession, AiChatMessage
from utils.ai_provider import get_ai_provider
from utils.reporting import month_format


def _utcnow():
    """Naive UTC now, replacing deprecated datetime.utcnow().

    The models' default timestamps are naive UTC; keep the same convention
    so existing rows and new rows stay directly comparable.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

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

    # 区间必须放在「YYYY年M月」之前：否则 "2024年1月1日至2024年3月31日"
    # 会被年月正则截断成 2024 年 1 月。
    # 用 findall 而非 fromisoformat：后者要求月份、日期必须补零，
    # 而大模型与用户常写 "2024-1-1"，直接解析会抛 ValueError 落回 None。
    if re.search(r'至|到|~|～|—|－', expr):
        found = re.findall(r'(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?', expr)
        if len(found) >= 2:
            try:
                s = date(*(int(x) for x in found[0]))
                e = date(*(int(x) for x in found[-1]))
                return (s, e) if s <= e else (e, s)
            except ValueError:
                pass

    # "YYYY年M月"
    match = re.match(r'^(\d{4})年(\d{1,2})月?$', expr)
    if match:
        y, m = int(match.group(1)), int(match.group(2))
        try:
            return date(y, m, 1), _get_month_end(y, m)
        except ValueError:
            return None, None

    # "YYYY年"
    match = re.match(r'^(\d{4})年$', expr)
    if match:
        y = int(match.group(1))
        return date(y, 1, 1), date(y, 12, 31)

    # 单日："YYYY-MM-DD" / "YYYY-M-D" / "YYYY/M/D" / "YYYY年M月D日"
    single = re.match(r'^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?$', expr)
    if single:
        try:
            d = date(*(int(x) for x in single.groups()))
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
        messages = []
        if session_id:
            # 同一秒内多条消息时 created_at 相同，补 id 作为二级排序保证顺序稳定。
            history = AiChatMessage.query.filter_by(session_id=session_id).order_by(
                AiChatMessage.created_at.desc(), AiChatMessage.id.desc()
            ).limit(9).all()
            # 路由层是「先落库用户消息、再分析」，最新一条就是当前提问。
            # 去掉它，避免把同一句话重复喂给模型。
            if history and history[0].role == 'user' \
                    and (history[0].content or '').strip() == query.strip():
                history = history[1:]
            for msg in reversed(history[:8]):
                if msg.role in ('user', 'assistant') and msg.content:
                    messages.append({'role': msg.role, 'content': msg.content})
            # 对话历史须以 user 开头，否则部分兼容接口会拒绝请求。
            while messages and messages[0]['role'] != 'user':
                messages.pop(0)
        messages.append({'role': 'user', 'content': query + '\n\n' + FIELD_DESCRIPTIONS})
        response = provider.chat(messages, max_tokens=512, system=INTENT_SYSTEM_PROMPT)
        parsed = provider.parse_json_response(response) if response else None
        if parsed and 'intent_type' in parsed:
            intent_type = parsed['intent_type']
            parameters = parsed.get('parameters', {}) or {}

    # Step 2: Fallback / 白名单校验（模型可能返回未定义的意图名）
    if intent_type not in INTENT_DESCRIPTIONS:
        intent_type, fallback_params = fallback_intent_recognition(query)
        if not parameters:
            parameters = fallback_params

    # Step 3: Parse dates
    start_date = None
    end_date = None
    date_range_note = None

    # Check if LLM returned date strings
    raw_start = parameters.get('start_date') if isinstance(parameters, dict) else None
    raw_end = parameters.get('end_date') if isinstance(parameters, dict) else None

    if raw_start:
        start_date, _ = parse_date_expression(str(raw_start))
    if raw_end:
        _, end_date = parse_date_expression(str(raw_end))

    # If no dates were extracted, try parsing the full query for common expressions
    if not start_date and not end_date:
        for expr in ['本月', '上月', '今年', '近12个月', '近6个月', '近3个月']:
            if expr in query:
                start_date, end_date = parse_date_expression(expr)
                break

    # 未指定日期时按「最近有数据的月份」统计，而不是硬编码本月。
    # 线上数据可能整体落在历史月份，默认「本月」会让每个快捷提问都返回空图。
    if not start_date and not end_date and intent_type in ('project_income', 'expense_structure', 'profit_loss'):
        data_min, data_max = get_data_date_range()
        if data_max:
            start_date = date(data_max.year, data_max.month, 1)
            end_date = _get_month_end(data_max.year, data_max.month)
            date_range_note = (
                f'数据覆盖 {data_min.isoformat()} 至 {data_max.isoformat()}，'
                f'本次按最近有数据月份 {start_date.strftime("%Y-%m")} 统计'
            )

    # Step 4: Execute SQL template query
    chart_type, chart_data = execute_query(intent_type, start_date, end_date)

    # Step 5: Generate reply text
    reply_text = generate_reply(
        intent_type, chart_type, chart_data, query,
        start_date=start_date, end_date=end_date, date_range_note=date_range_note,
    )

    return {
        'intent_type': intent_type,
        'parameters': parameters,
        'resolved_date_range': {
            'start_date': start_date.isoformat() if start_date else None,
            'end_date': end_date.isoformat() if end_date else None,
        },
        'date_range_note': date_range_note,
        'chart_type': chart_type,
        'chart_data': chart_data,
        'reply_text': reply_text,
    }


def get_data_date_range():
    """Return (min_date, max_date) of all transactions, or (None, None)."""
    row = db.session.query(
        func.min(Transaction.date), func.max(Transaction.date)
    ).first()
    if not row or not row[0]:
        return None, None
    return row[0], row[1]


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

    base_query = Transaction.query
    if date_filters:
        base_query = base_query.filter(*date_filters)

    if intent_type == 'project_income':
        return _query_project_income(base_query)
    elif intent_type == 'expense_structure':
        return _query_expense_structure(base_query)
    elif intent_type == 'trend':
        return _query_trend(start_date, end_date)
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

    rows = [(r[0], float(r[1] or 0), float(r[2] or 0)) for r in results if r[0]]
    top_n = 20
    top_rows = rows[:top_n]
    other_rows = rows[top_n:]
    labels = [r[0] for r in top_rows]
    incomes = [r[1] for r in top_rows]
    expenses = [r[2] for r in top_rows]
    if other_rows:
        labels.append('其他')
        incomes.append(sum(r[1] for r in other_rows))
        expenses.append(sum(r[2] for r in other_rows))

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

    rows = [(r[0], float(r[1] or 0)) for r in results if r[0]]
    top_n = 10
    top_rows = rows[:top_n]
    other_rows = rows[top_n:]
    labels = [r[0] for r in top_rows]
    values = [r[1] for r in top_rows]
    if other_rows:
        labels.append('其他')
        values.append(sum(r[1] for r in other_rows))

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


def _query_trend(start_date=None, end_date=None):
    """Monthly aggregation → line chart."""
    if start_date or end_date:
        date_filters = []
        if start_date:
            date_filters.append(Transaction.date >= start_date)
        if end_date:
            date_filters.append(Transaction.date <= end_date)
        month_expr = month_format(Transaction.date).label('month')
        rows = db.session.query(
            month_expr,
            func.coalesce(func.sum(Transaction.income), 0),
            func.coalesce(func.sum(Transaction.expense), 0),
        ).filter(*date_filters).group_by(month_expr).order_by(month_expr).all()
        trends = [{'month': r[0], 'income': float(r[1] or 0), 'expense': float(r[2] or 0)} for r in rows]
    else:
        # 不按「日历近 6 个月」补零：数据若集中在历史月份，那样只会得到六根空柱。
        # 直接取真实存在交易的最近 6 个月。
        month_expr = month_format(Transaction.date).label('month')
        rows = db.session.query(
            month_expr,
            func.coalesce(func.sum(Transaction.income), 0),
            func.coalesce(func.sum(Transaction.expense), 0),
        ).group_by(month_expr).order_by(month_expr.desc()).limit(6).all()
        trends = [
            {'month': r[0], 'income': float(r[1] or 0), 'expense': float(r[2] or 0)}
            for r in reversed(rows)
        ]

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


def _is_empty_chart(chart_type, chart_data):
    """Whether a query produced no analysable rows."""
    if not chart_data:
        return True
    if chart_type == 'table':
        return not chart_data.get('table')
    return not chart_data.get('labels')


def _empty_data_reply(start_date, end_date):
    """Explain an empty result and point the user at the period that has data."""
    data_min, data_max = get_data_date_range()
    if data_min is None or data_max is None:
        return '系统中尚无交易数据，请先导入流水后再使用 AI 分析。'

    period = ''
    if start_date and end_date:
        period = f'查询区间 {start_date.isoformat()} 至 {end_date.isoformat()} 内'

    return (
        f'{period}没有查询到可分析的数据。\n'
        f'当前流水覆盖 {data_min.isoformat()} 至 {data_max.isoformat()}，'
        f'可尝试提问「{data_max.year}年{data_max.month}月各项目收入」'
        f'或「{data_max.year}年支出结构分析」。'
    )


def generate_reply(intent_type, chart_type, chart_data, query,
                   start_date=None, end_date=None, date_range_note=None):
    """Generate a text reply based on intent type and query results.

    If AI provider is available, use LLM to generate natural language response.
    Otherwise, use template-based responses.
    """
    # 一般性问题不查库，直接给能力说明
    if chart_type is None or intent_type == 'general':
        return _template_reply(intent_type, chart_data)

    # 空结果不再交给大模型：否则会生成一大段「数据缺失」的报告，
    # 用户会误以为功能坏了。
    if _is_empty_chart(chart_type, chart_data):
        return _empty_data_reply(start_date, end_date)

    provider = get_ai_provider()

    if provider:
        data_summary = json.dumps(chart_data, ensure_ascii=False)
        period = ''
        if start_date and end_date:
            period = f'统计区间：{start_date.isoformat()} 至 {end_date.isoformat()}'
        if date_range_note:
            period = (period + '；' if period else '') + date_range_note

        system_prompt = f"""你是一个财务数据分析助手。根据以下查询结果，用简洁的中文生成一段数据分析报告。

查询类型: {intent_type}
用户问题: {query}
{period}

数据:
{data_summary}

要求:
1. 用简洁流畅的中文描述
2. 突出关键数据（最高/最低、对比关系）
3. 控制在3-5句话
4. 数字用千位分隔符格式化
5. 输出纯文本，不要使用 Markdown 标记（**、#、- 列表等），不要写标题"""

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
        datasets = chart_data.get('datasets', [])
        incomes = datasets[0].get('data', []) if datasets else []
        expenses = datasets[1].get('data', []) if len(datasets) > 1 else []
        if not trends:
            return '没有可用的趋势数据。'

        lines = ['最近有数据月份的收支趋势：']
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

    # Update session's updated_at（用 db.session.get 取代已弃用的 Query.get）
    session = db.session.get(AiChatSession, session_id)
    if session:
        session.updated_at = _utcnow()

    db.session.commit()
    return msg
