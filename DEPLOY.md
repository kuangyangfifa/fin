# LEXUE财务管理系统 - 部署文档

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
| 密钥 | `/home/fin/fin/.env`（`DEEPSEEK_*`、`AI_PROVIDER=deepseek`、`SECRET_KEY`，被 `.gitignore` 忽略） |
| 数据库迁移版本 | `d712567bfa3f`（head，含 `ai_chat_sessions` / `ai_chat_messages`）；部署脚本每次自动 `flask db upgrade` |
| 品牌资源 | `static/img/logo-full.png`（侧边栏、登录页）与 `logo-mark.png`（favicon）；退费模块 `refund/public/assets/logo-full.png` 为同一份文件。系统名称由 `config.py` 的 `APP_NAME` 统一控制，默认 `LEXUE财务管理系统`，可用 `.env` 的 `APP_NAME` 覆盖 |
| AI 月报缓存 | `/home/fin/fin/instance/ai_reports/YYYY-MM.json`（不入库，可随时删除后重新生成） |
| Nginx 超时 | 主模块 `/` 的 `proxy_send_timeout` / `proxy_read_timeout` 为 **180s**，与 AI 月报 `AI_REPORT_TIMEOUT=150` 配套；退费模块保持 60s |
| 测试 | `/root/miniconda3/bin/python -m pytest tests/ -q`（pytest 8.3.2，测试环境强制禁用真实模型调用） |
| 备份 | `/home/fin/backups/`（初始备份 `initial-20261105/`；每日 `daily/fin-backup-*.tar.gz`；升级前快照 `pre-deploy-*`；手工备份 `manual/`） |

**常用命令**

```bash
# 日常更新（幂等，含部署前快照、数据库迁移、9 项健康检查）
cd /home/fin/fin && git pull origin main && ./deploy/deploy-existing.sh

# 回归测试（无需网络，测试环境已强制关闭真实大模型调用）
cd /home/fin/fin && /root/miniconda3/bin/python -m pytest tests/ -q

# 服务状态 / 日志
systemctl status fin fin-refund nginx
journalctl -u fin -u fin-refund -n 100 --no-pager

# 每日备份（crontab 02:10 已配置；WAL 安全，勿直接 cp .db）
./deploy/backup.sh
```

**注意事项**

1. **域名 `lexueisland.site` 尚在管局审核、ICP 备案未生效**（2026-11-10 用户确认），任何端口用域名访问均被阿里云边缘拦截返回 403；当前仅 `http://101.200.231.62:5050` 可用，签字链接地址已设为 `http://101.200.231.62:5050/refund`。备案生效后按下方「备案生效后的 HTTPS 切换」执行，不要手工只改 `publicBaseUrl`。
2. **微信登录采用「免注册进入」，长期不启用公众号网页授权**（2026-11-10 确认，详见下方专节）。财务后台「微信登录」面板请勿填 AppID/AppSecret。
3. 退费模块写锁是进程内锁，`fin-refund` **必须保持单实例**，不要扩容。
4. 回滚：`git reset --hard d8270c3` + 用 `/home/fin/backups/initial-20261105/` 恢复数据库与配置 + `systemctl restart fin`；退费服务停掉即可恢复旧站。
5. `deploy/deploy.sh` 与 `deploy/supervisor.conf.example` 面向「全新服务器 + venv + Supervisor」，**不适用于这台既有站点**，请勿执行。

### AI 对话分析（2026-11-10 修复上线）

入口：`http://101.200.231.62:5050/ai`（**仅管理员可见可用**）。

**此前不可用的三个根因，已全部修复**

| 根因 | 表现 | 修复 |
|---|---|---|
| `ai_chat_sessions` / `ai_chat_messages` 两表从未创建（`alembic_version` 为空，两个迁移均未在服务器执行） | 新建会话即 `OperationalError` → 500 | 备份数据库后 `flask db stamp 55b49e43fd3b` 标记基线，再 `flask db upgrade` 执行 `d712567bfa3f` 建表；`deploy-existing.sh` 第 4 步已内置幂等迁移逻辑，后续升级不会再漏 |
| `.env` 有 `DEEPSEEK_API_KEY` 但未设 `AI_PROVIDER`，`get_ai_provider()` 恒返回 None | 只有关键词兜底与模板话术，无真实 AI 意图识别 | `.env` 追加 `AI_PROVIDER=deepseek`（密钥已存在，无需新增）；真实调用实测返回正常 |
| AI 页面全部 `.ai-*` 类在 `custom.css` 中无定义，Chart.js / Bootstrap 全部依赖 jsdelivr CDN | 页面是无排版的裸 div 堆叠；国内浏览器若取不到 CDN，图表与布局一起失效 | 补齐整套 `.ai-` 样式；Chart.js 4.4.1、Bootstrap 5.3.2、Bootstrap Icons 1.11.1（含 woff2 字体）全部下载到 `static/vendor/`，模板改本地引用 |

**同时修复的功能性缺陷**

- 未指定日期时默认按「本月」统计，而线上 181 条流水全部集中在 **2026-04**，导致每个快捷提问都返回空图、AI 还会生成一大段「数据缺失」报告。现改为默认按**最近有数据的月份**统计，回复里标注实际区间；空结果直接给出数据覆盖范围与可用提问示例，不再调用模型。
- 趋势查询不再按日历近 6 个月补零柱，改为取真实有交易的最近 6 个月。
- 日期解析支持非补零写法（`2024-1-1`）、中文区间（`2024年1月1日至2024年3月31日`），且区间判断前置，不会被「YYYY年M月」规则截断。
- 历史消息去掉与当前提问重复的一条（路由层先落库再分析），并按 `id` 二级排序保证同一秒内的顺序稳定。
- 饼图悬浮提示改为兼容 `context.parsed` 数值（原固定取 `parsed.y`，饼图必然报错）。
- `clearChat()` 原先重建 `chartArea.innerHTML`，导致顶部缓存的 canvas / welcome 引用指向脱离 DOM 的旧节点，图表渲染到不可见画布上；现改为常驻双容器 + 实时查询节点。
- 空数据不再渲染空图表区；历史会话重放只渲染最后一张图；请求失败显示后端真实错误。
- `Query.get()` 与 `datetime.utcnow()` 弃用调用已替换（时间戳仍为 naive UTC，与既有数据一致）。

**配置与自查**

```bash
# .env 中必须存在（密钥本身不要写入任何文档或仓库）
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
AI_PROVIDER=deepseek
```

- 页面顶部状态条显示当前 provider / model / 配置状态；点「测试连通」会发一条极小的真实请求，返回「正常」即链路通。
- 接口：`GET /ai/status`（只返回配置摘要，**不返回密钥**）、`POST /ai/status/ping`。均需管理员登录。
- 状态为 `disabled` 表示未设 `AI_PROVIDER`，功能仍可用但只有关键词兜底；`error` 表示缺密钥或驱动初始化失败，看 `journalctl -u fin -n 100`。
- 依赖：`openai` Python 包（服务器已装 2.35.1）；`anthropic` 未安装，不影响 DeepSeek 通道。若切 Claude/Qwen 需先 `INSTALL_PIP=1 ./deploy/deploy-existing.sh` 或单独补装对应包。

**提问示例**

`各项目收入汇总`、`支出结构分析`、`收支趋势`、`盈亏概况`、`2026年4月各项目收入`、`2026年4月1日至2026年4月22日盈亏概况`。明确写出「本月」时仍严格按自然月统计；若该月无数据会提示数据覆盖范围，不会给出空图。

### AI 月度分析报告（2026-11-10 打通上线）

入口：报表分析 → AI月度分析报告，或直接访问 `http://101.200.231.62:5050/reports/ai-monthly`（登录用户可用）。

**此前不可用的四个原因**

| 问题 | 处理 |
|---|---|
| 页面默认月份是「当前自然月」，而线上流水集中在 2026-04，点生成必然是空月份 | 默认改为**最近一个有流水的月份**，并提供「有数据的月份」快捷下拉 |
| 空月份仍把全 0 数据交给模型，模型会凭空编造一份「分析报告」 | 后端 `count == 0` 直接短路，返回 `no_data` 与数据覆盖范围、可选月份，不调用模型 |
| 硬编码 `DeepSeekProvider`，与 `AI_PROVIDER` 配置脱节；未配置时报错含内部信息 | 统一走 `get_ai_provider(timeout=150)`，与 AI 对话助手共用配置；异常只回传统一文案，细节写 `journalctl -u fin` |
| Nginx `proxy_read_timeout 60s`，`max_tokens=4096` 的长报告必然被截断为 504 | 主模块 `/` 超时放宽到 **180s**（模板已同步）；`max_tokens` 收敛到 3000；前端 180s 超时中断并计时提示 |

**功能与约束**

- 报告按月份缓存到 `instance/ai_reports/YYYY-MM.json`，重复查看**不再重复计费**；数据指纹（笔数 + 收支合计）变化自动失效，页面提供「重新生成」强制刷新。缓存文件不入库，删除即恢复首次生成状态。
- 支持复制、下载 Markdown、打印；Markdown 按行渲染，标题与列表不再被包进 `<p>`（原实现会被浏览器强制闭合，排版错乱）。
- 报告页顶部显示 AI 配置状态与数据覆盖范围；未配置 `AI_PROVIDER` 时生成请求返回 503 与明确指引。
- 单次生成约 1-3 分钟，属同步长请求。Nginx 超时若被改回 60s 会出现 504，部署脚本已加入检测提示。

### 自动化测试（2026-11-10 建立）

```bash
cd /home/fin/fin
/root/miniconda3/bin/python -m pytest tests/ -q
```

- `config.py` 的 `TestingConfig` 显式清空 `AI_PROVIDER` 与三家密钥：服务器 `.env` 会被 `load_dotenv()` 读入，若不隔离，单测会真实调用 DeepSeek（慢、计费、结果不稳定）。需要验证 LLM 路径的用例一律用 `unittest.mock` 注入假驱动。
- `tests/test_ai.py`：会话/消息/图表主流程、日期解析（非补零、中文单日与区间、非法日期）、权限隔离、空库提示、默认按最近有数据月份、历史消息去重。
- `tests/test_ai_monthly.py`：月份默认值、非法月份 400、空月份短路、生成与缓存落盘、缓存命中跳过模型、强制重生成、未配置驱动 503、异常信息脱敏、Prompt 章节编号连续。
- `pytest==8.3.2` 已在 `requirements.txt`；服务器用 `/root/miniconda3/bin/pip install pytest==8.3.2` 单独安装，避免整份 requirements 重装影响已上线依赖。

### 微信内登录（当前正式方案，2026-11-10 确认长期使用）

**结论：不启用公众号网页授权登录，长期使用「免注册进入」，不改代码、不改服务器配置。**

公众号为订阅号 / 未认证，按微信官方规则**不具备网页授权接口权限**（仅已微信认证的服务号有「网页授权域名」配置入口）。此外网页授权域名只支持 https、不支持 IP 与端口、需 ICP 备案且新备案满 24 小时、校验文件须放在域名根目录。因此**备案通过也不会自动解锁微信身份登录**，除非另行升级为认证服务号并补齐 HTTPS，本次决定不升级。

**给老师的使用说明（可直接转发）**

> 退费收款单填写入口：http://101.200.231.62:5050/refund/
> 请在微信中打开。首次进入选「免注册进入」，填写本人姓名和手机号后 4 位即可自动开通，无需注册账号、无需密码；之后在同一微信里再次打开会直接进入工作台，不必再登录。
> 单据填好后点「复制签字链接」转发给主管、校方，对方在微信里打开即可签字，无需登录。
> 请勿清除微信浏览器缓存；更换手机或清除缓存后需重新填写一次姓名与手机尾号。

**管理员须知**

- 财务后台「微信登录设置」保持 `AppID` / `AppSecret` 为空（`configured=false`）。一旦填入，前端会在微信内默认选中「微信一键登录」，点击后 `redirect_uri` 为 IP:5050，微信返回「redirect_uri 参数错误」，反而破坏现有可用入口。
- 当前开关：`nameLogin=true`、`nameLoginNeedPhone4=true`（`/home/fin/refund-data/config.json`）。手机后 4 位用于区分同名老师，不建议关闭。
- 登录态由前端 `localStorage.rf_token` 持久化，启动时调 `/me` 校验，有效则直接进入工作台；失效才回登录页。无需服务端改动。
- 微信内访问 HTTP + IP 链接一般可正常打开，但微信可能提示「非微信官方网页」；**不要改发未备案域名链接**（会被 403 拦截）。

**已发现、将来才需处理的坑**

后台「域名校验文件托管」把 `MP_verify_*.txt` 内容存进 `config.json`、由 Node 在 `/MP_verify_xxx.txt` 返回；但当前 Nginx 把域名根 `/` 反代到 Flask，实测 `/MP_verify_test.txt` 为 404，只有 `/refund/MP_verify_test.txt` 为 200，而微信只认域名根路径。若将来升级认证服务号并切 HTTPS，需统一这两套机制（Nginx 层把 `/MP_verify_*.txt` 反代到 Node，或按 `nginx-https.conf.example` 由 Nginx 直接托管文件），否则网页授权域名校验失败。

### 备案生效后的 HTTPS 切换（暂缓，域名仍在管局审核；脚本已备好）

**当前状态（2026-11-10）**：`lexueisland.site` 已解析到本机，但**备案仍在管局审核**，公网按 Host 访问被阿里云边缘 `Beaver` 拦截（403 Non-compliance ICP Filing，阻断 ID `00000000006012457343`）。纯 IP:80 与 IP:5050 为 200，服务器内部带域名 Host 访问 80 为 200，证明拦截在阿里云公网入口层、与 Nginx 无关。此阶段属正常审核等待，无需提交工单；审核通过且白名单同步后再执行下列步骤（官方口径为通过后约 7 小时至 1 个工作日）。

可提前处理的一项：**公网 TCP 443 不通**。服务器 firewalld 未运行、iptables INPUT 为 ACCEPT、无进程监听 443，且故障表现为超时（非 RST），判断为**阿里云 ECS 安全组未放行入方向 443**。可在 ECS 控制台安全组添加 `TCP 443 / 0.0.0.0/0` 入方向规则，否则备案解除后 HTTPS 仍无法访问。证书签发走 80 端口 webroot 通道，已实测可读取验证文件。

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
| 5 | 微信后台配置（**本次不执行**） | 当前公众号为订阅号/未认证，无网页授权权限。仅当升级为认证服务号后，才把 `MP_verify_XXXXXXXX.txt` 放到 `/usr/share/nginx/html/`（不入库）、在财务后台填 AppID/AppSecret、公众号「网页授权域名」填 `lexueisland.site`，重启 `fin-refund` |

设计约束：

- **保留 5050 HTTP 入口**，此前已发出的 `http://101.200.231.62:5050/refund/...` 签字链接继续可用；确认旧链接全部失效后再考虑关闭。
- **不启用 HSTS**：HSTS 按主机名生效（不含端口），会把 `http://lexueisland.site:5050` 也强制升级，导致旧链接失效。
- 80 端口保留 `/.well-known/acme-challenge/` 例外，不影响 Let's Encrypt 续期；该例外已实测可从域名 Host 读取验证文件。
- 80 与 443 均托管 `MP_verify_*.txt`（正则 location，优先于 301 与反代）。**注意这是 Nginx 文件系统托管**，与后台面板把内容存 `config.json` 是两套机制；若真要启用网页授权，须二选一：文件放 `/usr/share/nginx/html/`，或改 Nginx 反代到 Node，不要两边各填一半。
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

### Q1: `flask db upgrade` 报错找不到表 / 重复建表？
因为当前迁移文件缺少早期基础表的创建脚本。全新部署请先用 `db.create_all()`（见第四节）再 `flask db stamp head`。**既有站点**（如 `/home/fin/fin`）不要手工执行裸 upgrade：`alembic_version` 为空但表结构已含基线内容时，会重复建表报「table already exists」。直接跑 `./deploy/deploy-existing.sh`，脚本会先做 WAL 安全备份、按实际结构自动 stamp 基线，再 `flask db upgrade`，全过程幂等。

### Q2: 页面中文乱码？
确保服务器系统locale支持 UTF-8，且 Gunicorn/Python 运行环境编码为 UTF-8。

### Q3: 上传 Excel 报错？
Nginx 配置中确认设置了 `client_max_body_size 16M;`（与代码中 `MAX_CONTENT_LENGTH` 一致）。
