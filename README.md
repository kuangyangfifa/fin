# 💼 公司账户日流水管理系统 (Web版)

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Bootstrap 5](https://img.shields.io/badge/Bootstrap-5-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white)](https://getbootstrap.com/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

基于 Flask 开发的现代 Web 版公司账户流水管理系统。它不仅能帮助您高效地记录和追踪每日收支，还提供了强大的数据分析和权限管理功能，旨在取代传统的 Excel 手工记账。

---

## ✨ 核心特性

### 🔐 安全与权限
- **多用户认证**：内置用户登录系统，采用 Werkzeug 高强度哈希加密。
- **RBAC 权限**：区分管理员与普通用户，管理员可进行用户管理和系统配置。

### 💰 财务管理
- **多账户追踪**：支持无限量创建账户，独立计算各账户初始与当前余额。
- **智能流水录入**：支持收入/支出记录，输入金额后**自动重新计算**历史及后续余额。
- **多维度筛选**：支持按日期范围、账户类型、关键字、备注分类进行精确查询。

### 🏷️ 灵活的备注系统
- **分级分类**：支持两级联动的分级备注（如：大类-小类），满足复杂的报表分类需求。
- **动态下拉选择**：可自定义备注选项，录入流水时只需点击选择，提高录入效率。

### 🎨 前端优化计划 (2026-04)
- **Dashboard 可视化**：引入 Chart.js，展示月度收支趋势与账户资产分布。
- **移动端深度适配**：流水列表支持卡片式流转，优化手机端记账体验。
- **交互性能增强**：优化 note1/note2 联动逻辑，增加表单实时校验与 UI 动效。
- **视觉品牌化**：重构登录页与全局视觉规范，对标工业级财务系统。

### 📊 数据交互
- **Excel 批量导入**：支持从 Excel 模板批量导入历史流水。
- **一键导出**：将任何查询结果实时导出为标准 Excel 报表。

---

## 🛠️ 技术架构

- **后端**: Flask 3.0 + Flask-SQLAlchemy (ORM) + Flask-Migrate (迁移)
- **前端**: Bootstrap 5 + Bootstrap Icons + Responsive Design (适配移动端)
- **数据库**: 支持 SQLite (轻量级) 和 PostgreSQL (生产级)
- **Excel**: openpyxl 实现高性能读写

---

## 🚀 快速开始

### 1. 环境准备
确保已安装 Python 3.8+。建议使用虚拟环境：

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### 2. 安装依赖
```bash
cd web
pip install -r requirements.txt
```

### 3. 初始化数据库
系统支持使用 Flask-Migrate 管理数据库：

```bash
# 初始化并创建本地数据库
flask db upgrade
```
> [!TIP]
> 如果您是首次运行且未配置迁移，也可以在 Flask Shell 中运行 `db.create_all()`。

### 4. 创建管理员
运行 CLI 命令创建您的第一个超级用户：
```bash
flask create-admin
# 根据提示输入用户名和密码
```

### 5. 启动应用
```bash
python app.py
```
访问 [http://localhost:5000](http://localhost:5000) 即可开始记账。

---

## 📦 生产部署建议

在生产环境中，建议使用 **Gunicorn** 搭配反向代理（如 Nginx）：

```bash
# 使用 4 个工作进程启动
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app('production')"
```

### 核心环境变量
| 变量名 | 必填 | 说明 | 示例 |
|--------|:---:|------|------|
| `SECRET_KEY` | 是 | 生产环境必须修改，用于 Session 安全 | `your-random-secret-key` |
| `DATABASE_URL` | 否 | 数据库连接字符串 | `postgresql://user:pass@localhost/db` |
| `FLASK_ENV` | 否 | 运行模式 | `production` / `development` |

---

## 📂 目录结构预览

```text
web/
├── app.py                  # 应用工厂与路由注册
├── models.py               # 数据库模型定义 (User, Account, Transaction等)
├── config.py               # 分环境配置文件
├── migrate_data.py         # ⚠️ 用于从旧版(PyQt5)迁移数据的工具
├── utils/                  # 工具类 (Excel处理、装饰器)
├── templates/              # Jinja2 网页模板
└── static/                 # 静态资源 (CSS, JS, Images)
```

---

## 📝 使用指南

1. **账户预设**：首次使用请先到“账户管理”创建账户并设置初始余额。
2. **备注配置**：在“选项管理”中预设常用的分类备注，极大缩短记账耗时。
3. **数据导入**：点击“数据导入”，下载标准模板，按格式填写后批量上传。

---

## ⚖️ 许可证

本项目基于 [MIT License](LICENSE) 开源。
