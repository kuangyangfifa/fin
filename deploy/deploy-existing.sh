#!/usr/bin/env bash
# fin-remark 双模块「既有站点平滑升级」脚本（systemd 版，幂等）
#
# 适用：服务器已运行旧版 Flask 站点，代码在 /home/fin/fin，
#       用 systemd fin.service + miniconda Python + Nginx 5050 反代，
#       数据库在 <APP_DIR>/instance/finance_web.db（被 .gitignore 忽略）。
#
# 与 deploy/deploy.sh 的区别：不建 venv、不依赖 Supervisor、
#       不用 www-data 用户、不创建空的 finance.db。
#       数据库会执行 Alembic 迁移（幂等），因此新增表无需再手工补建。
#
# 用法：
#   cd /home/fin/fin && git pull origin main
#   sudo ./deploy/deploy-existing.sh
#
# 可覆盖变量：
#   APP_DIR        代码目录，默认 /home/fin/fin
#   PY             Python 解释器，默认 /root/miniconda3/bin/python
#   REFUND_DATA    退费数据目录，默认 /home/fin/refund-data
#   BACKUP_DIR     备份目录，默认 /home/fin/backups
#   ADMIN_KEY      首次初始化退费财务后台密码（config.json 已存在时忽略）
#   PUBLIC_BASE_URL 首次初始化对外地址（config.json 已存在时忽略）
#   INSTALL_PIP=1  额外执行 pip install -r requirements.txt（默认跳过）
#
# 回滚：用 $BACKUP_DIR 下最近一次快照恢复数据库、退费数据与配置，
#       再执行 git reset --hard <旧提交> && systemctl restart fin。

set -euo pipefail

APP_DIR="${APP_DIR:-/home/fin/fin}"
PY="${PY:-/root/miniconda3/bin/python}"
REFUND_DATA="${REFUND_DATA:-/home/fin/refund-data}"
BACKUP_DIR="${BACKUP_DIR:-/home/fin/backups}"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/conf.d/finance.conf}"
INSTALL_PIP="${INSTALL_PIP:-0}"

echo "========== 既有站点双模块升级 $(date) =========="
[ -f "$APP_DIR/app.py" ]            || { echo "错误：未找到 $APP_DIR/app.py"; exit 1; }
[ -f "$APP_DIR/refund/server.js" ]  || { echo "错误：未找到退费模块，请先 git pull"; exit 1; }
[ -x "$PY" ]                        || { echo "错误：Python 不可用：$PY"; exit 1; }
command -v node >/dev/null          || { echo "错误：缺少 Node.js（需 16+）"; exit 1; }
command -v systemctl >/dev/null     || { echo "错误：本脚本要求 systemd"; exit 1; }

mkdir -p "$BACKUP_DIR" "$REFUND_DATA/forms" "$REFUND_DATA/uploads" /home/fin/logs

# 1. 部署前全量快照（代码版本、数据库、退费数据、Nginx/Systemd 配置）
echo "[1/7] 生成部署前快照..."
STAMP="$(date +%Y%m%d-%H%M%S)"
SNAP="$BACKUP_DIR/pre-deploy-$STAMP"
mkdir -p "$SNAP"
(cd "$APP_DIR" && git rev-parse HEAD > "$SNAP/git-head.txt" 2>/dev/null || true)
[ -f "$APP_DIR/instance/finance_web.db" ] && cp -a "$APP_DIR/instance/finance_web.db" "$SNAP/" || true
[ -d "$REFUND_DATA" ] && tar -czf "$SNAP/refund-data.tar.gz" -C "$REFUND_DATA" . 2>/dev/null || true
[ -f "$NGINX_CONF" ] && cp -a "$NGINX_CONF" "$SNAP/finance.conf" || true
[ -f /etc/systemd/system/fin.service ] && cp -a /etc/systemd/system/fin.service "$SNAP/" || true
[ -f /etc/systemd/system/fin-refund.service ] && cp -a /etc/systemd/system/fin-refund.service "$SNAP/" || true
echo "   快照：$SNAP"
ls -1dt "$BACKUP_DIR"/pre-deploy-* 2>/dev/null | tail -n +11 | xargs -r rm -rf

# 2. 由主模块设计令牌生成退费主题覆盖层
echo "[2/7] 同步 UI 设计令牌..."
"$PY" "$APP_DIR/deploy/sync-theme.py"

# 3. Python 依赖（服务器已装齐时默认跳过，避免联网等待）
if [ "$INSTALL_PIP" = "1" ]; then
  echo "[3/7] 安装 Python 依赖..."
  "$PY" -m pip install -r "$APP_DIR/requirements.txt"
else
  echo "[3/7] 跳过依赖安装（如需补装：INSTALL_PIP=1）"
fi

# 4. 数据库：WAL 安全备份 + Alembic 迁移（幂等）
echo "[4/7] 校验并迁移 Flask 数据库..."
DB_FILE="$APP_DIR/instance/finance_web.db"
if [ -f "$DB_FILE" ]; then
  echo "   已存在：$DB_FILE（保持原路径，不设置 DATABASE_URL）"
  "$PY" - "$DB_FILE" "$SNAP/finance_web-pre-migrate.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)   # 在线 WAL 安全备份，迁移前的最后一道保险
dst.close(); src.close()
PY
  # 旧站点从未跑过迁移，alembic_version 为空但表结构已含基线内容。
  # 直接 upgrade 会重复建表/加列报错，需先按实际结构 stamp 到对应版本。
  BASELINE="$(cd "$APP_DIR" && "$PY" - "$DB_FILE" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
version = c.execute("select version_num from alembic_version").fetchone() \
    if 'alembic_version' in tables else None
if version and version[0]:
    print('managed')
else:
    cols = {r[1] for r in c.execute('pragma table_info(transactions)')} \
        if 'transactions' in tables else set()
    if {'ai_chat_sessions', 'ai_chat_messages'} <= tables:
        print('head')
    elif 'note_options' in tables and {'note3', 'note4', 'note5'} <= cols:
        print('55b49e43fd3b')
    else:
        print('unknown')
PY
)"
  case "$BASELINE" in
    managed)
      echo "   alembic_version 已有记录，跳过基线标记" ;;
    55b49e43fd3b|head)
      echo "   alembic_version 为空，按现有结构标记基线：$BASELINE"
      (cd "$APP_DIR" && "$PY" -m flask --app app db stamp "$BASELINE") ;;
    *)
      echo "错误：数据库结构与迁移基线不匹配，已停止部署。请人工核对后重试" >&2
      echo "      迁移前备份：$SNAP/finance_web-pre-migrate.db" >&2
      exit 1 ;;
  esac
else
  echo "   未发现数据库，按默认路径初始化..."
  (cd "$APP_DIR" && "$PY" -c \
    "from app import create_app; from models import db; a=create_app('production'); a.app_context().push(); db.create_all(); print('   数据库表已创建')")
  (cd "$APP_DIR" && "$PY" -m flask --app app db stamp head)
fi
(cd "$APP_DIR" && "$PY" -m flask --app app db upgrade)
echo "   数据库已同步至迁移 head"

# 5. 退费模块配置与 SECRET_KEY（均仅首次写入）
echo "[5/7] 校验运行时配置..."
if [ ! -f "$REFUND_DATA/config.json" ]; then
  ADMIN_KEY="${ADMIN_KEY:-}" PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}" node -e '
    const fs = require("fs"), crypto = require("crypto");
    const cfg = {
      adminKey: process.env.ADMIN_KEY || crypto.randomBytes(12).toString("hex"),
      seq: 0,
      wechat: { appId: "", appSecret: "", nameLogin: true, nameLoginNeedPhone4: true, verifyFiles: {} },
      publicBaseUrl: process.env.PUBLIC_BASE_URL || ""
    };
    fs.writeFileSync(process.argv[1], JSON.stringify(cfg, null, 2), "utf8");
    console.log("   财务后台初始密码：" + cfg.adminKey + "（仅显示这一次）");
  ' "$REFUND_DATA/config.json"
else
  echo "   退费配置已存在，跳过初始化"
fi

ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  umask 077; : > "$ENV_FILE"
fi
if ! grep -q '^SECRET_KEY=' "$ENV_FILE"; then
  printf 'SECRET_KEY=%s\n' "$(openssl rand -hex 32)" >> "$ENV_FILE"
  echo "   已追加 SECRET_KEY 到 $ENV_FILE（现存会话需重新登录）"
fi
chmod 600 "$ENV_FILE"
if ! grep -q '^AI_PROVIDER=' "$ENV_FILE"; then
  echo "   提示：未配置 AI_PROVIDER，AI 对话分析仅使用关键词兜底"
  echo "         启用方式：在 $ENV_FILE 追加 AI_PROVIDER=deepseek（密钥已存在时）"
fi

# 6. 服务配置与重启
echo "[6/7] 安装服务配置并重启..."
install -m 644 "$APP_DIR/deploy/fin-refund.service" /etc/systemd/system/fin-refund.service
if [ -f "$APP_DIR/deploy/fin.service.example" ] && \
   ! cmp -s "$APP_DIR/deploy/fin.service.example" /etc/systemd/system/fin.service; then
  install -m 644 "$APP_DIR/deploy/fin.service.example" /etc/systemd/system/fin.service
  echo "   已更新 fin.service（workers 4 → 2）"
fi
if ! grep -q 'location /refund/' "$NGINX_CONF" 2>/dev/null; then
  echo "错误：$NGINX_CONF 未包含 location /refund/，请先放置 deploy/nginx-existing.conf.example" >&2
  echo "      参考：cp deploy/nginx-existing.conf.example $NGINX_CONF && nginx -t" >&2
  exit 1
fi
nginx -t >/dev/null || { echo "错误：nginx 配置校验失败"; exit 1; }
# 脚本不覆盖既有 Nginx 配置（站点可能另有定制），只提示超时要求。
# AI 月报生成是长请求，60s 默认值会导致 504。
if ! grep -q 'proxy_read_timeout 180s' "$NGINX_CONF" 2>/dev/null; then
  echo "   提示：$NGINX_CONF 未设置 proxy_read_timeout 180s，AI 月度报告可能 504 超时"
  echo "        请参照 deploy/nginx-existing.conf.example 手工调整后 nginx -t && systemctl reload nginx"
fi
systemctl daemon-reload
systemctl enable fin-refund >/dev/null 2>&1 || true
systemctl restart fin
systemctl restart fin-refund
systemctl reload nginx

# 7. 健康检查（任一失败即非零退出，便于 CI/人工发现）
echo "[7/7] 健康检查..."
sleep 3
FAILED=0
check() {
  if curl -fsS -o /dev/null --max-time 8 "$2"; then
    echo "   $1：正常"
  else
    echo "   $1：失败（$2）" >&2
    FAILED=1
  fi
}
check "Gunicorn 登录页"        "http://127.0.0.1:8000/login"
check "Node 退费首页"          "http://127.0.0.1:3000/refund/"
check "Node 退费接口"          "http://127.0.0.1:3000/refund/api/auth/wechat/status"
check "Nginx 主模块(5050)"     "http://127.0.0.1:5050/login"
check "Nginx 退费入口(5050)"   "http://127.0.0.1:5050/refund/"
check "Nginx 退费接口(5050)"   "http://127.0.0.1:5050/refund/api/auth/wechat/status"
check "Chart.js 本地资源"      "http://127.0.0.1:8000/static/vendor/chart.umd.min.js"
check "Bootstrap 本地资源"     "http://127.0.0.1:8000/static/vendor/bootstrap.min.css"
check "品牌 Logo 本地资源"     "http://127.0.0.1:8000/static/img/logo-full.png"
if [ "$FAILED" -ne 0 ]; then
  echo "健康检查未通过：journalctl -u fin -u fin-refund -n 100；回滚快照在 $SNAP" >&2
  exit 1
fi

echo "========== 升级完成 $(date) =========="
echo "对外地址：http://<域名或IP>:5050/ 与 http://<域名或IP>:5050/refund/"
echo "服务状态：systemctl status fin fin-refund"
echo "回滚快照：$SNAP"
