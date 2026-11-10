# 公司账户日流水管理系统 - 部署文档

> 本文档为 Flask 主模块单模块通用部署说明。**当前仓库已升级为「财务主系统 + 退费审核」双模块架构**；通用新装说明见仓库外根 `DEPLOY.md` v2.0，实际已上线的服务器请以下面「线上实况速查」为准。

## 线上实况速查（2026-11-05 已在阿里云 ECS 部署完成）

| 项 | 实际值 |
|---|---|
| 服务器 | Alibaba Cloud Linux 3，`101.200.231.62`，2 核 1.8G |
| 代码目录 | `/home/fin/fin`（Git 仓库根，`app.py` 直接在内，**不是** `/home/fin/app`） |
| Python | `/root/miniconda3/bin/python`（全局环境，无 venv） |
| 进程守护 | systemd `fin.service`（Gunicorn 2 workers，`127.0.0.1:8000`）、`fin-refund.service`（Node，`127.0.0.1:3000`） |
| 对外入口 | Nginx `/etc/nginx/conf.d/finance.conf` 监听 **5050**；`/refund/` 反代 3000，其余反代 8000 |
| 访问地址 | `http://101.200.231.62:5050/` 与 `http://101.200.231.62:5050/refund/` |
| 数据库 | `/home/fin/fin/instance/finance_web.db`（**不要设置 `DATABASE_URL`**，否则会指向空库） |
| 退费数据 | `/home/fin/refund-data`（单据、账号、附件、`config.json`） |
| 密钥 | `/home/fin/fin/.env`（`DEEPSEEK_*`、`SECRET_KEY`，被 `.gitignore` 忽略） |
| 备份 | `/home/fin/backups/`（初始备份 `initial-20261105/`；每日 `daily/fin-backup-*.tar.gz`） |

**常用命令**

```bash
# 日常更新（幂等，含部署前快照 + 6 项健康检查）
cd /home/fin/fin && git pull origin main && ./deploy/deploy-existing.sh

# 服务状态 / 日志
systemctl status fin fin-refund nginx
journalctl -u fin -u fin-refund -n 100 --no-pager

# 每日备份（crontab 02:10 已配置；WAL 安全，勿直接 cp .db）
./deploy/backup.sh
```

**注意事项**

1. **域名 `lexueisland.site` 的 ICP 备案白名单尚未在阿里云生效**（域名已解析、用户侧称备案已通过，但仍被边缘拦截），任何端口用域名访问均返回 403；当前仅 IP:5050 可用，签字链接地址已设为 `http://101.200.231.62:5050/refund`。白名单生效后：按下方「备案生效后的 HTTPS 切换」执行，不要手工只改 `publicBaseUrl`。
2. **微信网页授权暂不可用**（要求 80/443 + 已备案域名），备案完成后在财务后台「微信登录」面板配置 AppID/AppSecret 与 `MP_verify_*.txt`。
3. 退费模块写锁是进程内锁，`fin-refund` **必须保持单实例**，不要扩容。
4. 回滚：`git reset --hard d8270c3` + 用 `/home/fin/backups/initial-20261105/` 恢复数据库与配置 + `systemctl restart fin`；退费服务停掉即可恢复旧站。
5. `deploy/deploy.sh` 与 `deploy/supervisor.conf.example` 面向「全新服务器 + venv + Supervisor」，**不适用于这台既有站点**，请勿执行。

### 备案生效后的 HTTPS 切换（已备好脚本，待备案拦截解除后执行）

**当前状态（2026-11-10）**：`lexueisland.site` 已解析到本机，备案通过已超 1 个工作日，但公网按 Host 访问仍被阿里云边缘 `Beaver` 拦截（403 Non-compliance ICP Filing，阻断 ID `00000000006012457343`）。服务器内部带域名 Host 访问 80 为 200，证明拦截不在 Nginx。按阿里云官方说明，超 1 个工作日仍拦截需核查「接入商是否已添加阿里云」「备案类型是否为网站备案」，必要时附阻断 ID 提交工单。

另需提前处理：**公网 TCP 443 不通**，而服务器 firewalld 未运行、iptables INPUT 为 ACCEPT、无进程监听 443，且故障表现为超时（非 RST），判断为**阿里云 ECS 安全组未放行入方向 443**。请先在 ECS 控制台安全组添加 `TCP 443 / 0.0.0.0/0` 入方向规则，否则备案解除后 HTTPS 仍无法访问。证书签发用的是 80 端口 webroot 通道，已实测可读取验证文件。

前置确认（**必须在本机而非服务器执行**，服务器内部访问会走内网直通而误判）：

```bash
curl -I http://lexueisland.site/     # 不再返回 403 才可继续
```

| 顺序 | 命令 / 动作 | 说明 |
|---|---|---|
| 1 | 上述公网自测 | 403 时不要执行后续步骤，certbot 的 HTTP-01 验证必然失败 |
| 2 | `cd /home/fin/fin && git pull origin main` | 拉取出证书与切换脚本 |
| 3 | `CERTBOT_EMAIL='你的邮箱' ./deploy/issue-cert.sh` | 从 EPEL 装 certbot 1.22，webroot 签发，配置每日 03:25 自动续期 |
| 4 | `./deploy/switch-https.sh` | 自动备份 → 装 80 跳转 + 443 双模块路由 → 改 `publicBaseUrl` 为 `https://lexueisland.site/refund` → 5 项健康检查 |
| 5 | 微信后台配置 | 把公众号后台下载的 `MP_verify_XXXXXXXX.txt` 放到服务器 `/usr/share/nginx/html/`（该目录不入库），在财务后台「微信登录」面板填 AppID/AppSecret，公众号「网页授权域名」填 `lexueisland.site`，重启 `fin-refund` |

设计约束：

- **保留 5050 HTTP 入口**，此前已发出的 `http://101.200.231.62:5050/refund/...` 签字链接继续可用；确认旧链接全部失效后再考虑关闭。
- **不启用 HSTS**：HSTS 按主机名生效（不含端口），会把 `http://lexueisland.site:5050` 也强制升级，导致旧链接失效。
- 80 端口保留 `/.well-known/acme-challenge/` 例外，不影响 Let's Encrypt 续期；该例外已实测可从域名 Host 读取验证文件。
- 80 与 443 均托管 `MP_verify_*.txt`（正则 location，优先于 301 与反代），微信域名校验文件放 `/usr/share/nginx/html/` 即可，无需改 Nginx。
- 回滚：`./deploy/switch-https.sh --revert`（从 `/home/fin/backups/https-*` 恢复 Nginx 配置与退费配置）。

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
