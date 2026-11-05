# 公司账户日流水管理系统 - 部署文档

> 本文档为 Flask 主模块单模块部署说明。**当前仓库已升级为「财务主系统 + 退费审核」双模块架构**，服务器部署请以仓库根目录的 `DEPLOY.md`（v2.0）与 `deploy/` 下的配置示例为准。

## 一、环境要求

- **Python**: 3.10+
- **操作系统**: Linux / Windows Server / macOS
- **数据库**:
  - 开发/小型场景: SQLite（内置，无需单独安装）
  - 生产推荐: PostgreSQL 13+
- **Web 服务器**（生产环境）: Nginx + Gunicorn

---

## 二、代码部署

### 1. 拉取/上传代码

将代码上传到服务器目标目录，例如 `/opt/fin-remark/web`。

```bash
cd /opt/fin-remark/web
```

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

---

## 三、环境变量配置

生产环境必须配置以下环境变量（或通过 `.env` 文件导出）。

```bash
# 必填：生产环境密钥，必须设置且长度建议 >= 24
export SECRET_KEY="your-strong-random-secret-key-here"

# 必填：运行环境（development / production / testing）
export FLASK_ENV="production"

# 数据库（二选一）
# 方式 A：SQLite（简单场景，文件路径建议写绝对路径）
export DATABASE_URL="sqlite:///mnt/data/finance_web.db"

# 方式 B：PostgreSQL（推荐生产环境）
# export DATABASE_URL="postgresql://user:password@localhost:5432/finance_db"
```

> **注意**: `SECRET_KEY` 用于会话加密，一旦生产运行后请勿随意修改，否则所有登录会话会失效。

---

## 四、数据库初始化

> **重要提示**：当前代码库中 Alembic 迁移文件不完整，缺少 `users`、`accounts`、`transactions`、`note1_options` 等基础表的迁移脚本。**首次部署请使用 `flask db.create_all()` 方式初始化**，而非 `flask db upgrade`。

在虚拟环境激活状态下执行：

```bash
# 进入项目根目录（包含 app.py 的目录）
cd /opt/fin-remark/web

# 初始化数据库表结构
python -c "from app import create_app; app = create_app('production'); app.app_context().push(); from models import db; db.create_all()"
```

执行成功后，可通过以下方式验证表是否创建完整：

- **SQLite**：
  ```bash
  sqlite3 /mnt/data/finance_web.db ".tables"
  # 应看到：accounts, note1_options, note_options, transactions, users, alembic_version
  ```

- **PostgreSQL**：
  ```sql
  \dt
  ```

---

## 五、创建管理员账号

数据库初始化完成后，必须创建一个管理员账号才能登录系统。

```bash
flask create-admin --username admin
# 按提示输入密码
```

如需创建普通用户：

```bash
flask create-user --username alice
# 按提示输入密码
# 如需管理员权限，加上 --admin 参数
```

---

## 六、运行方式

### 方式 A：开发调试（不推荐生产使用）

```bash
python app.py
```

默认监听 `0.0.0.0:5050`。

### 方式 B：生产运行（推荐）

使用 Gunicorn 作为 WSGI 服务器：

```bash
gunicorn -w 4 -b 127.0.0.1:8000 "app:create_app('production')"
```

参数说明：
- `-w 4`: 4 个 worker 进程，可根据 CPU 核数调整（通常 `2 * CPU核心数 + 1`）
- `-b 127.0.0.1:8000`: 监听本机 8000 端口
- 外部通过 **Nginx 反向代理** 到此端口

#### Nginx 反向代理示例

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    client_max_body_size 16M;
}
```

> 建议配置 HTTPS（使用 Let's Encrypt 等证书），并在 Nginx 层强制跳转 `http -> https`。

---

## 七、部署后验证清单

1. **访问首页**：`http://your-domain.com/login`
2. **登录测试**：使用 `flask create-admin` 创建的账号密码登录
3. **功能验证**：
   - 创建账户
   - 录入流水（测试余额自动计算）
   - 查看报表（日报 / 月报 / 分类维度分析）
   - Excel 导入导出
4. **管理员功能**（仅限 admin 账号）：
   - 进入"备注选项管理"，添加项目/分类选项
   - 进入"用户管理"，创建/编辑/重置密码
5. **测试覆盖验证**（可选，部署前在测试环境执行）：
   ```bash
   python -m pytest tests/ -v
   ```

---

## 八、后续升级说明

- **仅代码更新，未改模型**：直接替换代码，重启 Gunicorn 即可，无需操作数据库。
- **若后续引入了模型变更**：建议统一补齐 Alembic 迁移文件后，再使用 `flask db migrate` + `flask db upgrade` 流程进行升级。

---

## 九、常见问题

### Q1: `flask db upgrade` 报错找不到表？
因为当前迁移文件缺少早期基础表的创建脚本。首次部署请使用 `db.create_all()`（见第四节）。

### Q2: 页面中文乱码？
确保服务器系统locale支持 UTF-8，且 Gunicorn/Python 运行环境编码为 UTF-8。

### Q3: 上传 Excel 报错？
Nginx 配置中确认设置了 `client_max_body_size 16M;`（与代码中 `MAX_CONTENT_LENGTH` 一致）。
