import os
from datetime import datetime, date
from calendar import monthrange
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required
from models import db, Account, Transaction, NoteOption, Note1Option
from utils.reporting import month_format, year_format
from utils.ai_provider import DeepSeekProvider

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


@reports_bp.route('/reports/ai-monthly', methods=['GET', 'POST'])
@login_required
def report_ai_monthly():
    """AI-powered monthly analysis report."""
    if request.method == 'POST':
        return _handle_ai_monthly_post()

    # GET: render page with month selector
    today = date.today()
    month = request.args.get('month', today.strftime('%Y-%m'))
    return render_template('report_ai_monthly.html', month=month)


def _handle_ai_monthly_post():
    """Handle POST request for AI monthly analysis."""
    try:
        data = request.get_json(silent=True) or {}
        month_str = data.get('month', date.today().strftime('%Y-%m'))

        try:
            year, month_num = map(int, month_str.split('-'))
            start_date = date(year, month_num, 1)
            _, last_day = monthrange(year, month_num)
            end_date = date(year, month_num, last_day)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': '无效的月份格式，请使用 YYYY-MM'}), 400

        # --- Query aggregated data for the month ---
        base_query = Transaction.query.filter(
            Transaction.date >= start_date,
            Transaction.date <= end_date
        )

        count = base_query.count()

        # Monthly totals
        income_total = base_query.with_entities(
            db.func.coalesce(db.func.sum(Transaction.income), 0)
        ).scalar()

        expense_total = base_query.with_entities(
            db.func.coalesce(db.func.sum(Transaction.expense), 0)
        ).scalar()

        monthly_summary = {
            'income': float(income_total),
            'expense': float(expense_total),
            'net': float(income_total - expense_total),
            'transaction_count': count,
        }

        # Previous month totals for comparison
        prev_month = month_num - 1
        prev_year = year
        if prev_month == 0:
            prev_month = 12
            prev_year -= 1
        prev_start = date(prev_year, prev_month, 1)
        _, prev_last_day = monthrange(prev_year, prev_month)
        prev_end = date(prev_year, prev_month, prev_last_day)
        prev_income = db.session.query(db.func.coalesce(db.func.sum(Transaction.income), 0)).filter(
            Transaction.date >= prev_start, Transaction.date <= prev_end
        ).scalar()
        prev_expense = db.session.query(db.func.coalesce(db.func.sum(Transaction.expense), 0)).filter(
            Transaction.date >= prev_start, Transaction.date <= prev_end
        ).scalar()
        prev_summary = {
            'income': float(prev_income),
            'expense': float(prev_expense),
            'net': float(prev_income - prev_expense),
        }

        # By account
        by_account = db.session.query(
            Account.account_name,
            db.func.coalesce(db.func.sum(Transaction.income), 0),
            db.func.coalesce(db.func.sum(Transaction.expense), 0),
        ).join(Account, Transaction.account_id == Account.id).filter(
            Transaction.date >= start_date,
            Transaction.date <= end_date
        ).group_by(Transaction.account_id).all()

        accounts_data = []
        for name, inc, exp in by_account:
            accounts_data.append({
                'name': name,
                'income': float(inc),
                'expense': float(exp),
                'net': float(inc - exp),
            })

        # By note1 (project)
        by_note1 = base_query.with_entities(
            Transaction.note1,
            db.func.coalesce(db.func.sum(Transaction.income), 0),
            db.func.coalesce(db.func.sum(Transaction.expense), 0),
        ).group_by(Transaction.note1).all()

        note1_data = []
        for val, inc, exp in by_note1:
            if val:
                note1_data.append({
                    'value': val,
                    'income': float(inc),
                    'expense': float(exp),
                    'net': float(inc - exp),
                })

        # By note2
        by_note2 = base_query.with_entities(
            Transaction.note2,
            db.func.coalesce(db.func.sum(Transaction.income), 0),
            db.func.coalesce(db.func.sum(Transaction.expense), 0),
        ).group_by(Transaction.note2).all()

        note2_data = []
        for val, inc, exp in by_note2:
            if val:
                note2_data.append({
                    'value': val,
                    'income': float(inc),
                    'expense': float(exp),
                    'net': float(inc - exp),
                    'total': float(inc + exp),
                })

        # By note3
        by_note3 = base_query.with_entities(
            Transaction.note3,
            db.func.coalesce(db.func.sum(Transaction.income), 0),
            db.func.coalesce(db.func.sum(Transaction.expense), 0),
        ).group_by(Transaction.note3).all()

        note3_data = []
        for val, inc, exp in by_note3:
            if val:
                note3_data.append({
                    'value': val,
                    'income': float(inc),
                    'expense': float(exp),
                    'net': float(inc - exp),
                })

        # By note4
        by_note4 = base_query.with_entities(
            Transaction.note4,
            db.func.coalesce(db.func.sum(Transaction.income), 0),
            db.func.coalesce(db.func.sum(Transaction.expense), 0),
        ).group_by(Transaction.note4).all()

        note4_data = []
        for val, inc, exp in by_note4:
            if val:
                note4_data.append({
                    'value': val,
                    'income': float(inc),
                    'expense': float(exp),
                    'net': float(inc - exp),
                })

        # By note5
        by_note5 = base_query.with_entities(
            Transaction.note5,
            db.func.coalesce(db.func.sum(Transaction.income), 0),
            db.func.coalesce(db.func.sum(Transaction.expense), 0),
        ).group_by(Transaction.note5).all()

        note5_data = []
        for val, inc, exp in by_note5:
            if val:
                note5_data.append({
                    'value': val,
                    'income': float(inc),
                    'expense': float(exp),
                    'net': float(inc - exp),
                })

        # --- Build the analysis prompt ---
        prompt = _build_analysis_prompt(
            month_str, monthly_summary, prev_summary,
            accounts_data, note1_data,
            note2_data, note3_data, note4_data, note5_data,
        )

        # --- Call DeepSeek ---
        api_key = current_app.config.get('DEEPSEEK_API_KEY', '') or os.environ.get('DEEPSEEK_API_KEY', '')
        if not api_key:
            return jsonify({'success': False, 'error': 'DeepSeek API 密钥未配置'}), 500

        base_url = current_app.config.get('DEEPSEEK_BASE_URL', '') or os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
        model = current_app.config.get('DEEPSEEK_MODEL')
        provider = DeepSeekProvider(api_key, base_url, model=model)

        system_prompt = (
            '你是一位资深财务分析师和企业经营顾问。'
            '请根据提供的月度财务数据，从公司经营者和老板的视角进行全面分析。'
            '使用专业但易懂的中文，注重数据洞察和 actionable 建议。'
            '请用清晰的章节结构呈现分析结果。'
        )

        result = provider.chat(
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=4096,
            system=system_prompt,
        )

        if not result:
            return jsonify({'success': False, 'error': 'AI 分析请求失败，请检查 API 密钥和网络连接'}), 500

        return jsonify({'success': True, 'analysis': result})
    except Exception as e:
        current_app.logger.exception('AI monthly analysis failed')
        return jsonify({'success': False, 'error': f'服务器内部错误: {str(e)}'}), 500


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

    lines = [f"## {month} 月度财务数据分析报告\n"]

    # Monthly overview
    lines.append("### 一、本月经营概览")
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

    # By account
    lines.append("### 二、各账户收支情况")
    for a in accounts:
        lines.append(
            f"- {a['name']}：收入 {_fmt(a['income'])}，"
            f"支出 {_fmt(a['expense'])}，净额 {_fmt(a['net'])}"
        )
    lines.append("")

    # By note1 (project)
    lines.append("### 三、按项目（note1）汇总")
    for n in _top_n_with_other(note1, top_n=30):
        lines.append(
            f"- {n['value']}：收入 {_fmt(n['income'])}，"
            f"支出 {_fmt(n['expense'])}，净额 {_fmt(n['net'])}"
        )
    lines.append("")

    # By note2 (category)
    if note2:
        total_flow = summary['income'] + summary['expense']
        lines.append("### 四、按类别（note2）汇总")
        for n in _top_n_with_other(note2, top_n=20):
            lines.append(
                f"- {n['value']}：收入 {_fmt(n['income'])}，"
                f"支出 {_fmt(n['expense'])}（占总流水 {_pct(n['total'], total_flow)}）"
            )
        lines.append("")

    # By note3/4/5
    for label, label_cn, data in [
        ('note3', '五', note3), ('note4', '六', note4), ('note5', '七', note5)
    ]:
        if data:
            lines.append(f"### {label_cn}、按{label}汇总")
            for n in _top_n_with_other(data, top_n=30):
                lines.append(
                    f"- {n['value']}：收入 {_fmt(n['income'])}，"
                    f"支出 {_fmt(n['expense'])}，净额 {_fmt(n['net'])}"
                )
            lines.append("")

    # Analysis request
    lines.append("### 分析要求")
    lines.append("请基于以上数据，从公司经营者和老板的视角，进行以下分析：")
    lines.append("1. **经营概览**：解读本月整体经营状况，收入/支出/净盈亏的变化趋势及原因推测")
    lines.append("2. **收入结构分析**：哪些项目/类别是主要收入来源，收入结构是否健康")
    lines.append("3. **支出结构分析**：主要支出项目，是否有异常或过高的支出")
    lines.append("4. **多维度交叉洞察**：结合 note1~note5 各维度，发现业务模式、季节性特征或潜在问题")
    lines.append("5. **风险与问题**：现金流风险、支出结构失衡、收入依赖单一项目等风险提示")
    lines.append("6. **经营建议**：给出 3-5 条具体、可操作的建议，帮助改善经营状况")
    lines.append("")
    lines.append("请用专业但易懂的语言，分章节呈现分析结果。")

    return '\n'.join(lines)
