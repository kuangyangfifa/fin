# 公司账户日流水管理系统 - Web版

基于 Flask 的 Web 版本公司账户日流水管理系统，支持多用户在线访问、流水编辑删除、Excel 导入导出等功能。

## 功能特性

- **用户认证**：支持多用户登录，密码加密存储
- **账户管理**：创建账户、修改账户名、删除空账户
- **流水录入**：支持收入/支出记录，自动计算余额
- **流水查询**：多条件筛选（日期范围、账户、关键字）
- **流水编辑**：支持修改历史记录，自动重新计算余额
- **流水删除**：支持删除记录，自动重新计算余额
- **Excel 导入导出**：支持批量导入和导出查询结果
- **响应式设计**：支持桌面和移动设备访问

## 技术栈

- **后端**：Flask 3.0 + Flask-SQLAlchemy + Flask-Login
- **数据库**：SQLite（开发）/ PostgreSQL（生产）
- **前端**：Bootstrap 5 + Bootstrap Icons
- **Excel 处理**：openpyxl

## 安装部署

### 1. 安装依赖

```bash
cd web
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
# 设置 Flask 应用
set FLASK_APP=app.py  # Windows
export FLASK_APP=app.py  # Linux/Mac

# 创建数据库表
flask shell
>>> from app import app
>>> from models import db
>>> with app.app_context():
...     db.create_all()
>>> exit()
```

### 3. 创建管理员用户

```bash
flask create-admin
# 按提示输入用户名和密码
```

### 4. 运行应用

```bash
# 开发模式
python app.py

# 或使用 Flask 命令
flask run
```

访问 http://localhost:5000 即可使用。

## 数据迁移

如需从旧版 PyQt5 桌面应用迁移数据：

```bash
# 确保旧版 finance.db 在父目录中
python migrate_data.py
```

## 生产部署

### 使用 Gunicorn

```bash
# 安装 Gunicorn（已包含在 requirements.txt）
pip install gunicorn

# 启动服务
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app('production')"
```

### 环境变量配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `SECRET_KEY` | 应用密钥 | dev-secret-key-change-in-production |
| `DATABASE_URL` | 数据库连接字符串 | sqlite:///finance_web.db |
| `FLASK_ENV` | 运行环境 | development |

### 使用 PostgreSQL

```bash
# 设置数据库连接字符串
export DATABASE_URL="postgresql://user:password@localhost/finance_db"
```

## 目录结构

```
web/
├── app.py                  # Flask 应用主入口
├── models.py               # 数据库模型
├── config.py               # 配置文件
├── requirements.txt        # Python 依赖
├── migrate_data.py         # 数据迁移脚本
├── README.md               # 本文件
├── utils/                  # 工具模块
│   ├── decorators.py       # 装饰器
│   └── excel_handler.py    # Excel 处理
└── templates/              # HTML 模板
    ├── base.html           # 基础模板
    ├── login.html          # 登录页
    ├── dashboard.html      # 首页/仪表盘
    ├── accounts.html       # 账户管理
    ├── transaction_add.html    # 流水录入
    ├── transaction_list.html   # 流水查询
    ├── transaction_edit.html   # 流水编辑
    └── transaction_import.html # Excel导入
```

## CLI 命令

```bash
# 创建管理员用户
flask create-admin

# 创建普通用户
flask create-user --username user1 --admin

# 列出所有用户
flask list-users
```

## 使用说明

### 首次使用

1. 访问登录页面，使用 `flask create-admin` 创建的管理员账号登录
2. 进入"账户管理"页面，创建至少一个账户
3. 进入"流水录入"页面，开始记录交易
4. 使用"流水查询"页面查看、编辑、删除记录

### Excel 导入

1. 先创建好所有需要的账户
2. 下载导入模板，按格式填写数据
3. 上传 Excel 文件进行导入

Excel 格式要求：
- 第一行为表头，不会被导入
- 日期格式：YYYY-MM-DD
- 账户名称必须与系统中完全一致
- 收入和支出不能同时为0

## 注意事项

1. **数据备份**：建议定期备份数据库文件
2. **并发编辑**：多用户同时编辑同一流水时，后保存的会覆盖先保存的
3. **余额计算**：编辑或删除流水后，系统会自动重新计算该账户的所有余额

## 许可证

MIT License
