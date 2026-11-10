import json
import os
import re
from calendar import monthrange
from datetime import datetime, date
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required
from sqlalchemy import func

from models import db, Account, Transaction, NoteOption, Note1Option
from utils.reporting import month_format, year_format
from utils.ai_analyzer import get_data_date_range
from utils.ai_provider import get_ai_provider

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/reports')
@login_required
def reports():
    """Report analysis page."""
    return render_template('reports.html')


@reports_bp.route('/reports/daily')
@login_required
def report_daily():
    """Daily report analysis - show each account's status per date."""
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    if not start_date_str:
        start_date_str = date.today().replace(day=1).strftime('%Y-%m-%d')
    if not end_date_str:
        end_date_str = date.today().strftime('%Y-%m-%d')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = date.today()

    all_accounts = Account.query.order_by(Account.account_name).all()
    account_map = {a.id: a.account_name for a in all_accounts}

    query = db.session.query(
        Transaction.date,
        Transaction.account_id,
        db.func.sum(Transaction.income).label('total_income'),
        db.func.sum(Transaction.expense).label('total_expense')
    ).filter(
        Transaction.date >= start_date,
        Transaction.date <= end_date
    ).group_by(Transaction.date, Transaction.account_id).order_by(Transaction.date, Transaction.account_id)

    daily_data = query.all()

    dates_data = {}
    for row in daily_data:
        date_key = row.date.strftime('%Y-%m-%d')
        if date_key not in dates_data:
            dates_data[date_key] = {
                'date': row.date,
                'accounts': {},
                'total_income': 0,
                'total_expense': 0
            }
        dates_data[date_key]['accounts'][row.account_id] = {
            'account_name': account_map.get(row.account_id, '未知'),
            'income': row.total_income or 0,
            'expense': row.total_expense or 0,
            'net': (row.total_income or 0) - (row.total_expense or 0)
        }
        dates_data[date_key]['total_income'] += row.total_income or 0
        dates_data[date_key]['total_expense'] += row.total_expense or 0

    return render_template('report_daily.html',
                           dates_data=dates_data,
                           accounts=all_accounts,
                           start_date=start_date_str,
                           end_date=end_date_str)


@reports_bp.route('/reports/monthly')
@login_required
def report_monthly():
    """Monthly report analysis - show all accounts per month."""
    year = request.args.get('year', date.today().year, type=int)

    all_accounts = Account.query.order_by(Account.account_name).all()
    account_map = {a.id: a.account_name for a in all_accounts}

    year_expr = year_format(Transaction.date)
    month_expr = month_format(Transaction.date)

    query = db.session.query(
        month_expr.label('month'),
        Transaction.account_id,
        db.func.sum(Transaction.income).label('total_income'),
        db.func.sum(Transaction.expense).label('total_expense')
    ).filter(
        year_expr == str(year)
    ).group_by(month_expr, Transaction.account_id).order_by(month_expr, Transaction.account_id)

    monthly_data = query.all()

    months_data = {}
    for row in monthly_data:
        month_key = row.month
        if month_key not in months_data:
            months_data[month_key] = {
                'month': row.month,
                'accounts': {},
                'total_income': 0,
                'total_expense': 0
            }
        months_data[month_key]['accounts'][row.account_id] = {
            'account_name': account_map.get(row.account_id, '未知'),
            'income': row.total_income or 0,
            'expense': row.total_expense or 0,
            'net': (row.total_income or 0) - (row.total_expense or 0)
        }
        months_data[month_key]['total_income'] += row.total_income or 0
        months_data[month_key]['total_expense'] += row.total_expense or 0

    return render_template('report_monthly.html',
                           months_data=months_data,
                           accounts=all_accounts,
                           year=year)


@reports_bp.route('/reports/by-note')
@login_required
def report_by_note():
    """Report analysis by note fields."""
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    note_field = request.args.get('note_field', 'note1')
    period_type = request.args.get('period_type', 'daily')
    note1_parent = request.args.get('note1_parent', '').strip()
    note1_child = request.args.get('note1_child', '').strip()

    if not start_date_str:
        start_date_str = date.today().replace(day=1).strftime('%Y-%m-%d')
    if not end_date_str:
        end_date_str = date.today().strftime('%Y-%m-%d')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = date.today()

    if note_field not in ['note1', 'note2', 'note3', 'note4', 'note5']:
        note_field = 'note1'

    if period_type == 'monthly':
        query = db.session.query(
            month_format(Transaction.date).label('period'),
            getattr(Transaction, note_field).label('note_value'),
            db.func.sum(Transaction.income).label('total_income'),
            db.func.sum(Transaction.expense).label('total_expense')
        ).filter(
            Transaction.date >= start_date,
            Transaction.date <= end_date
        )
    else:
        query = db.session.query(
            Transaction.date.label('period'),
            getattr(Transaction, note_field).label('note_value'),
            db.func.sum(Transaction.income).label('total_income'),
            db.func.sum(Transaction.expense).label('total_expense')
        ).filter(
            Transaction.date >= start_date,
            Transaction.date <= end_date
        )

    if note_field == 'note1':
        if note1_parent:
            prefix = note1_parent + '-'
            if note1_child:
                query = query.filter(Transaction.note1 == prefix + note1_child)
            else:
                query = query.filter(Transaction.note1.startswith(prefix))

    query = query.group_by('period', 'note_value').order_by('period', db.desc(db.func.sum(Transaction.income + Transaction.expense)))
    report_data = query.all()

    periods = {}
    for row in report_data:
        period_key = row.period
        if period_key not in periods:
            periods[period_key] = []
        periods[period_key].append({
            'note_value': row.note_value or '(空)',
            'income': row.total_income or 0,
            'expense': row.total_expense or 0,
            'net': (row.total_income or 0) - (row.total_expense or 0)
        })

    note_options = NoteOption.get_options_for_field(note_field)
    note1_options = Note1Option.get_all_options_dict()

    return render_template('report_by_note.html',
                           periods=periods,
                           note_field=note_field,
                           note_options=note_options,
                           note1_options=note1_options,
                           note1_parent=note1_parent,
                           note1_child=note1_child,
                           period_type=period_type,
                           start_date=start_date_str,
                           end_date=end_date_str)


# ---------------------------------------------------------------------------
# AI 月度分析报告
#
# 设计要点：
#   1. 默认选中「最近一个有流水的月份」，避免用户打开页面就落在空月份；
#   2. 空月份直接短路，不把全 0 数据交给大模型，杜绝模型凭空编造报告；
#   3. 使用统一的 get_ai_provider()，与 AI 对话助手共用同一份 AI_PROVIDER 配置；
#   4. 报告按月份缓存到 instance/ai_reports/，重复查看不再计费；
#      数据指纹（笔数 + 收支合计）变化时自动失效，也可由前端强制重新生成；
#   5. 长文本生成放宽单次超时，需与 Nginx proxy_read_timeout 配套调整。
# ---------------------------------------------------------------------------

AI_REPORT_TIMEOUT = 150
AI_REPORT_MAX_TOKENS = 3000
MONTH_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def _available_months():
    """返回数据库中实际有流水的月份，倒序，如 ['2026-04', '2026-03']。"""
    rows = db.session.query(
        func.distinct(month_format(Transaction.date))
    ).filter(Transaction.date.isnot(None)).all()
    return sorted({str(r[0]) for r in rows if r[0]}, reverse=True)


def _data_range_hint():
    start, end = get_data_date_range()
    return {
        'start': start.isoformat() if start else None,
        'end': end.isoformat() if end else None,
    }


def _ai_brief_status():
    """页面用的轻量配置检查，绝不回传密钥。"""
    cfg = current_app.config
    name = (cfg.get('AI_PROVIDER') or '').strip().lower()
    if not name:
        return {'ready': False, 'message': '未配置 AI_PROVIDER，请在 .env 中启用后重启服务'}
    key_field = {
        'deepseek': 'DEEPSEEK_API_KEY',
        'qwen': 'QWEN_API_KEY',
        'claude': 'CLAUDE_API_KEY',
    }.get(name)
    if key_field and not cfg.get(key_field):
        return {'ready': False, 'message': f'缺少 {key_field}，请在 .env 中补齐后重启服务'}
    return {'ready': True, 'message': f'AI 服务已就绪（{name}）'}


def _report_cache_path(month_str):
    directory = Path(current_app.instance_path) / 'ai_reports'
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f'{month_str}.json'


@reports_bp.route('/reports/ai-monthly', methods=['GET', 'POST'])
@login_required
def report_ai_monthly():
    """AI 月度分析报告：GET 渲染页面，POST 生成或读取缓存报告。"""
    if request.method == 'POST':
        return _handle_ai_monthly_post()

    months = _available_months()
    default_month = months[0] if months else date.today().strftime('%Y-%m')
    month = request.args.get('month', default_month)
    options = list(months)
    if month not in options:
        options.insert(0, month)

    info = _ai_brief_status()
    return render_template(
        'report_ai_monthly.html',
        month=month,
        months=options,
        data_months=months,
        data_range=_data_range_hint(),
        ai_ready=info['ready'],
        ai_message=info['message'],
    )


def _month_totals(query):
    row = query.with_entities(
        db.func.coalesce(db.func.sum(Transaction.income), 0),
        db.func.coalesce(db.func.sum(Transaction.expense), 0),
    ).one()
    return float(row[0] or 0), float(row[1] or 0)


def _collect_monthly_dataset(base_query, start_date, end_date, year, month_num, summary):
    """汇总月度数据，返回可直接展开给 _build_analysis_prompt 的字典。"""
    prev_month = month_num - 1
    prev_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1
    prev_start = date(prev_year, prev_month, 1)
    prev_end = date(prev_year, prev_month, monthrange(prev_year, prev_month)[1])
    prev_income, prev_expense = _month_totals(Transaction.query.filter(
        Transaction.date >= prev_start, Transaction.date <= prev_end
    ))
    prev = {
        'income': prev_income,
        'expense': prev_expense,
        'net': prev_income - prev_expense,
    }

    by_account = db.session.query(
        Account.account_name,
        db.func.coalesce(db.func.sum(Transaction.income), 0),
        db.func.coalesce(db.func.sum(Transaction.expense), 0),
    ).join(Account, Transaction.account_id == Account.id).filter(
        Transaction.date >= start_date, Transaction.date <= end_date
    ).group_by(Transaction.account_id).all()
    accounts = [
        {'name': name, 'income': float(inc), 'expense': float(exp), 'net': float(inc - exp)}
        for name, inc, exp in by_account
    ]

    notes = {}
    for field in ('note1', 'note2', 'note3', 'note4', 'note5'):
        rows = base_query.with_entities(
            getattr(Transaction, field),
            db.func.coalesce(db.func.sum(Transaction.income), 0),
            db.func.coalesce(db.func.sum(Transaction.expense), 0),
        ).group_by(getattr(Transaction, field)).all()
        notes[field] = [
            {
                'value': val,
                'income': float(inc),
                'expense': float(exp),
                'net': float(inc - exp),
                'total': float(inc + exp),
            }
            for val, inc, exp in rows if val
        ]

    return {
        'summary': summary,
        'prev': prev,
        'accounts': accounts,
        'note1': notes['note1'],
        'note2': notes['note2'],
        'note3': notes['note3'],
        'note4': notes['note4'],
        'note5': notes['note5'],
    }


def _handle_ai_monthly_post():
    """生成月度 AI 分析报告。"""
    data = request.get_json(silent=True) or {}
    month_str = str(data.get('month') or '').strip()
    force = bool(data.get('force'))

    if not MONTH_RE.match(month_str):
        return jsonify({'success': False, 'error': '无效的月份格式，请使用 YYYY-MM'}), 400

    year, month_num = map(int, month_str.split('-'))
    start_date = date(year, month_num, 1)
    end_date = date(year, month_num, monthrange(year, month_num)[1])

    try:
        months = _available_months()
        data_range = _data_range_hint()
        base_query = Transaction.query.filter(
            Transaction.date >= start_date, Transaction.date <= end_date
        )
        count = base_query.count()

        # 空月份：不调用大模型，直接给出可操作提示
        if count == 0:
            hint = ''
            if data_range['start']:
                hint = f"当前库内流水覆盖 {data_range['start']} 至 {data_range['end']}"
                if months:
                    hint += f"；可选月份：{'、'.join(months[:6])}"
            return jsonify({
                'success': True,
                'no_data': True,
                'month': month_str,
                'message': f'{month_str} 没有流水记录，无法生成分析报告。{hint}',
                'available_months': months,
                'data_range': data_range,
            })

        income_total, expense_total = _month_totals(base_query)
        fingerprint = f'{count}|{income_total:.2f}|{expense_total:.2f}'

        cache_path = _report_cache_path(month_str)
        if not force and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding='utf-8'))
                if cached.get('fingerprint') == fingerprint and cached.get('analysis'):
                    cached['cached'] = True
                    return jsonify(cached)
            except (OSError, ValueError):
                current_app.logger.warning('AI 月报缓存读取失败，将重新生成', exc_info=True)

        provider = get_ai_provider(timeout=AI_REPORT_TIMEOUT)
        if provider is None:
            return jsonify({
                'success': False,
                'error': 'AI 服务未配置或驱动初始化失败，请联系管理员检查 .env 中的 AI_PROVIDER 与密钥',
            }), 503

        summary = {
            'income': income_total,
            'expense': expense_total,
            'net': income_total - expense_total,
            'transaction_count': count,
        }
        dataset = _collect_monthly_dataset(
            base_query, start_date, end_date, year, month_num, summary
        )
        prompt = _build_analysis_prompt(month_str, **dataset)

        system_prompt = (
            '你是一位资深财务分析师和企业经营顾问。'
            '请严格依据提供的月度财务数据，从公司经营者的视角进行分析。'
            '不得编造数据、不得臆测未提供的业务背景；数据不足时明确说明。'
            '时间表述一律使用具体年月（如 2026年4月），不要使用「本月」「上月」等相对时间。'
            '使用专业但易懂的中文，用 Markdown 分章节呈现，给出具体可执行的建议。'
        )
        result = provider.chat(
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=AI_REPORT_MAX_TOKENS,
            system=system_prompt,
        )
        if not result:
            return jsonify({'success': False, 'error': 'AI 分析请求失败，请稍后重试或查看服务日志'}), 502

        payload = {
            'success': True,
            'analysis': result,
            'month': month_str,
            'model': getattr(provider, 'model', ''),
            'provider': (current_app.config.get('AI_PROVIDER') or '').lower(),
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'transaction_count': count,
            'summary': summary,
            'fingerprint': fingerprint,
            'cached': False,
        }
        # 原子写入，避免多 worker 并发读到半截 JSON
        tmp = cache_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, cache_path)
        return jsonify(payload)
    except Exception:
        # 不把底层异常原文回传前端，避免泄露密钥、路径等内部信息
        current_app.logger.exception('AI monthly analysis failed')
        return jsonify({
            'success': False,
            'error': '生成报告时发生服务器内部错误，请稍后重试或查看服务日志',
        }), 500


def _fmt(v):
    """Format a number as CNY string."""
    return f"¥{v:,.2f}"


def _pct(part, total):
    """Calculate percentage."""
    if total == 0:
        return '0.0%'
    return f"{part / total * 100:.1f}%"


def _top_n_with_other(data, top_n=20, value_key='value'):
    if not data:
        return []
    sorted_data = sorted(
        data,
        key=lambda x: (x.get('income', 0) or 0) + (x.get('expense', 0) or 0),
        reverse=True,
    )
    top = sorted_data[:top_n]
    other = sorted_data[top_n:]
    if not other:
        return top
    agg = {value_key: '其他'}
    for k in ('income', 'expense', 'net', 'total'):
        if any(k in d for d in other) or any(k in d for d in top):
            agg[k] = float(sum((d.get(k, 0) or 0) for d in other))
    top.append(agg)
    return top


def _build_analysis_prompt(month, summary, prev, accounts, note1, note2, note3, note4, note5):
    """Build the analysis prompt with aggregated financial data."""
    cn_nums = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
    section = 0

    def heading(title):
        nonlocal section
        section += 1
        return f"### {cn_nums[section - 1]}、{title}"

    lines = [f"## {month} 月度财务数据分析报告\n"]

    lines.append(heading('本月经营概览'))
    lines.append(f"- 总交易笔数：{summary['transaction_count']} 笔")
    lines.append(f"- 总收入：{_fmt(summary['income'])}")
    lines.append(f"- 总支出：{_fmt(summary['expense'])}")
    lines.append(f"- 净盈亏：{_fmt(summary['net'])}")
    lines.append("")
    lines.append("#### 与上月对比")
    lines.append(f"- 上月总收入：{_fmt(prev['income'])}")
    lines.append(f"- 上月总支出：{_fmt(prev['expense'])}")
    lines.append(f"- 上月净盈亏：{_fmt(prev['net'])}")
    inc_change = summary['income'] - prev['income']
    exp_change = summary['expense'] - prev['expense']
    lines.append(f"- 收入变化：{'+' if inc_change >= 0 else ''}{_fmt(inc_change)}")
    lines.append(f"- 支出变化：{'+' if exp_change >= 0 else ''}{_fmt(exp_change)}")
    lines.append("")

    lines.append(heading('各账户收支情况'))
    for a in accounts:
        lines.append(
            f"- {a['name']}：收入 {_fmt(a['income'])}，"
            f"支出 {_fmt(a['expense'])}，净额 {_fmt(a['net'])}"
        )
    lines.append("")

    lines.append(heading('按项目（note1）汇总'))
    for n in _top_n_with_other(note1, top_n=30):
        lines.append(
            f"- {n['value']}：收入 {_fmt(n['income'])}，"
            f"支出 {_fmt(n['expense'])}，净额 {_fmt(n['net'])}"
        )
    lines.append("")

    if note2:
        total_flow = summary['income'] + summary['expense']
        lines.append(heading('按类别（note2）汇总'))
        for n in _top_n_with_other(note2, top_n=20):
            lines.append(
                f"- {n['value']}：收入 {_fmt(n['income'])}，"
                f"支出 {_fmt(n['expense'])}（占总流水 {_pct(n['total'], total_flow)}）"
            )
        lines.append("")

    for label, data in [('note3', note3), ('note4', note4), ('note5', note5)]:
        if data:
            lines.append(heading(f'按{label}汇总'))
            for n in _top_n_with_other(data, top_n=30):
                lines.append(
                    f"- {n['value']}：收入 {_fmt(n['income'])}，"
                    f"支出 {_fmt(n['expense'])}，净额 {_fmt(n['net'])}"
                )
            lines.append("")

    lines.append("### 分析要求")
    lines.append("请基于以上数据，从公司经营者和老板的视角，进行以下分析：")
    lines.append("1. **经营概览**：解读本月整体经营状况，收入/支出/净盈亏的变化趋势及原因推测")
    lines.append("2. **收入结构分析**：哪些项目或类别是主要收入来源，收入结构是否健康")
    lines.append("3. **支出结构分析**：主要支出项目，是否有异常或过高的支出")
    lines.append("4. **多维度交叉洞察**：结合各备注维度，发现业务模式、季节性特征或潜在问题")
    lines.append("5. **风险与问题**：现金流风险、支出结构失衡、收入依赖单一项目等风险提示")
    lines.append("6. **经营建议**：给出 3-5 条具体、可操作的建议，帮助改善经营状况")
    lines.append("")
    lines.append("所有结论必须引用上文给出的具体数字；数据不支持的判断请明确标注为推测，不得编造。")
    lines.append("请用专业但易懂的语言，用 Markdown 分章节呈现分析结果。")

    return '\n'.join(lines)
