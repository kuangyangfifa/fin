#!/usr/bin/env bash
# fin-remark 双模块部署 / 更新脚本（在服务器执行，可重复运行，不覆盖既有数据）
#
# 用法：
#   ADMIN_KEY='你的财务后台密码' PUBLIC_BASE_URL='https://your-domain.com/refund' ./deploy/deploy.sh
# 常用环境变量：
#   APP_DIR   代码目录，默认 /home/fin/app（Git 仓库根，内含 app.py 与 refund/）
#   VENV      Python 虚拟环境，默认 /home/fin/venv
#   DATA_DIR  数据目录，默认 /home/fin/data
#   SKIP_PIP=1 跳过 Python 依赖安装（仅更新代码时用）
#
# 前置：代码已 git pull；Nginx 与 Supervisor 配置已按 deploy/*.example 部署过一次。

set -euo pipefail

APP_DIR="${APP_DIR:-/home/fin/app}"
VENV="${VENV:-/home/fin/venv}"
DATA_DIR="${DATA_DIR:-/home/fin/data}"
LOGS_DIR="${LOGS_DIR:-/home/fin/logs}"
REFUND_DATA="$DATA_DIR/refund"
SKIP_PIP="${SKIP_PIP:-0}"

echo "========== fin-remark 部署开始 $(date) =========="
[ -f "$APP_DIR/app.py" ] || { echo "错误：未找到 $APP_DIR/app.py，请确认仓库已克隆到该目录"; exit 1; }
[ -f "$APP_DIR/refund/server.js" ] || { echo "错误：未找到退费模块，请先执行 git pull"; exit 1; }
command -v node >/dev/null || { echo "错误：缺少 Node.js（需 16+）"; exit 1; }
if [ -x "$VENV/bin/python" ]; then PY="$VENV/bin/python"; else PY=python3; fi

mkdir -p "$DATA_DIR" "$REFUND_DATA/forms" "$REFUND_DATA/uploads" "$LOGS_DIR" "$DATA_DIR/backups"

# 1. 由主模块设计令牌生成退费模块主题覆盖层
echo "[1/6] 同步 UI 设计令牌..."
"$PY" "$APP_DIR/deploy/sync-theme.py"

# 2. Python 依赖
if [ "$SKIP_PIP" != "1" ]; then
  echo "[2/6] 安装 Python 依赖..."
  if [ -x "$VENV/bin/pip" ]; then "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"; else "$PY" -m pip install -r "$APP_DIR/requirements.txt"; fi
else
  echo "[2/6] 跳过依赖安装（SKIP_PIP=1）"
fi

# 3. Flask 数据库（仅首次创建，绝不覆盖既有数据）
if [ ! -f "$DATA_DIR/finance.db" ]; then
  echo "[3/6] 初始化 Flask 数据库..."
  (cd "$APP_DIR" && DATABASE_URL="sqlite:///$DATA_DIR/finance.db" "$PY" -c \
    "from app import create_app; from models import db; a=create_app('production'); a.app_context().push(); db.create_all(); print('数据库表已创建')")
else
  echo "[3/6] 数据库已存在，跳过初始化"
fi

# 4. 退费模块配置（仅首次创建；密码不写入仓库和 Supervisor 配置）
if [ ! -f "$REFUND_DATA/config.json" ]; then
  echo "[4/6] 初始化退费模块配置..."
  ADMIN_KEY="${ADMIN_KEY:-}" PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}" node -e '
    const fs = require("fs"), crypto = require("crypto");
    const p = process.argv[1];
    const cfg = {
      adminKey: process.env.ADMIN_KEY || crypto.randomBytes(12).toString("hex"),
      seq: 0,
      wechat: { appId: "", appSecret: "", nameLogin: true, nameLoginNeedPhone4: true, verifyFiles: {} },
      publicBaseUrl: process.env.PUBLIC_BASE_URL || ""
    };
    fs.writeFileSync(p, JSON.stringify(cfg, null, 2), "utf8");
    console.log("   财务后台初始密码：" + cfg.adminKey + "（请妥善保存，仅显示这一次）");
  ' "$REFUND_DATA/config.json"
else
  echo "[4/6] 退费模块配置已存在，跳过"
fi

# 5. 权限与重启
echo "[5/6] 调整权限并重启服务..."
if [ "$(id -u)" = "0" ]; then
  chown -R www-data:www-data "$DATA_DIR" "$LOGS_DIR" 2>/dev/null || true
fi
if command -v supervisorctl >/dev/null; then
  supervisorctl reread >/dev/null 2>&1 || true
  supervisorctl update >/dev/null 2>&1 || true
  supervisorctl restart fin: || echo "   警告：Supervisor 进程组未启动，请检查 /etc/supervisor/conf.d/fin-remark.conf"
else
  echo "   警告：未检测到 supervisorctl，请手动重启 Gunicorn 与 Node 服务"
fi

# 6. 健康检查
echo "[6/6] 健康检查..."
sleep 2
check() {
  local name="$1" url="$2"
  if curl -fsS -o /dev/null --max-time 8 "$url"; then echo "   $name：正常"; else echo "   $name：失败（$url）"; fi
}
check "Flask 主模块" "http://127.0.0.1:8000/login"
check "退费模块页面" "http://127.0.0.1:3000/refund/"
check "退费模块接口" "http://127.0.0.1:3000/refund/api/auth/wechat/status"

echo "========== 部署完成 $(date) =========="
echo "提示：如需修改对外地址，编辑 $REFUND_DATA/config.json 的 publicBaseUrl，或在财务后台「微信登录」面板修改，改完执行 supervisorctl restart fin-refund。"
