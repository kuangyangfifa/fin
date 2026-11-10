#!/usr/bin/env bash
# 备案生效且证书签发后：切换正式 HTTPS 入口（幂等）
#
# 用法：
#   ./deploy/switch-https.sh              # 启用 80 跳转 + 443 双模块，改签字链接为 https
#   ./deploy/switch-https.sh --revert     # 回滚到 5050 HTTP 入口，恢复原 publicBaseUrl
#
# 前置：./deploy/issue-cert.sh 已成功，证书位于 /etc/letsencrypt/live/
# 保留 5050 入口，已发出的 http://IP:5050/refund/ 签字链接继续可用。

set -euo pipefail

APP_DIR="${APP_DIR:-/home/fin/fin}"
DOMAIN="${DOMAIN:-lexueisland.site}"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/conf.d/finance.conf}"
REFUND_DATA="${REFUND_DATA:-/home/fin/refund-data}"
BACKUP_DIR="${BACKUP_DIR:-/home/fin/backups}"
CFG="$REFUND_DATA/config.json"
NEW_URL="${PUBLIC_BASE_URL:-https://$DOMAIN/refund}"
OLD_URL="${FALLBACK_BASE_URL:-http://101.200.231.62:5050/refund}"

set_url() {
  local url="$1"
  URL="$url" node -e '
    const fs = require("fs");
    const p = process.argv[1];
    const c = JSON.parse(fs.readFileSync(p, "utf8"));
    c.publicBaseUrl = process.env.URL;
    fs.writeFileSync(p, JSON.stringify(c, null, 2), "utf8");
    console.log("   publicBaseUrl =", c.publicBaseUrl);
  ' "$CFG"
}

# ---------- 回滚 ----------
if [ "${1:-}" = "--revert" ]; then
  echo "========== 回滚到 HTTP:5050 $(date) =========="
  LAST=$(ls -1dt "$BACKUP_DIR"/https-* 2>/dev/null | head -1 || true)
  if [ -n "$LAST" ] && [ -f "$LAST/finance.conf" ]; then
    cp -a "$LAST/finance.conf" "$NGINX_CONF"
    cp -a "$LAST/config.json" "$CFG"
    echo "   已从 $LAST 恢复 Nginx 与退费配置"
  else
    cp -a "$APP_DIR/deploy/nginx-existing.conf.example" "$NGINX_CONF"
    set_url "$OLD_URL"
    echo "   未找到切换前备份，已用 5050 模板恢复"
  fi
  nginx -t >/dev/null
  systemctl reload nginx
  systemctl restart fin-refund
  echo "回滚完成，请从公网验证 http://101.200.231.62:5050/refund/"
  exit 0
fi

# ---------- 切换 ----------
echo "========== 切换 HTTPS 入口 $(date) =========="
[ -f "$CERT_DIR/fullchain.pem" ] || { echo "错误：证书不存在，请先执行 ./deploy/issue-cert.sh"; exit 1; }
[ -f "$CERT_DIR/privkey.pem" ]   || { echo "错误：私钥不存在"; exit 1; }
[ -f "$CFG" ]                    || { echo "错误：未找到 $CFG"; exit 1; }
[ -f "$APP_DIR/deploy/nginx-https.conf.example" ] || { echo "错误：缺少 HTTPS 配置模板，请先 git pull"; exit 1; }

# 1. 备份当前可运行状态
STAMP="$(date +%Y%m%d-%H%M%S)"
SNAP="$BACKUP_DIR/https-$STAMP"
mkdir -p "$SNAP"
cp -a "$NGINX_CONF" "$SNAP/finance.conf"
cp -a "$CFG" "$SNAP/config.json"
(cd "$APP_DIR" && git rev-parse HEAD > "$SNAP/git-head.txt" 2>/dev/null) || true
echo "   切换前备份：$SNAP"

# 2. 安装 Nginx 配置并校验
install -m 644 "$APP_DIR/deploy/nginx-https.conf.example" "$NGINX_CONF"
if ! nginx -t 2>&1; then
  echo "Nginx 校验失败，自动还原" >&2
  cp -a "$SNAP/finance.conf" "$NGINX_CONF"
  exit 1
fi

# 3. 退费模块对外地址改为 https 域名
set_url "$NEW_URL"

# 4. 生效
systemctl reload nginx
systemctl restart fin-refund
sleep 2

# 5. 健康检查（服务器内部用 --resolve 命中本机 443）
echo "健康检查..."
FAILED=0
check() {
  local name="$1" code
  shift
  code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$@" 2>/dev/null || echo 000)
  if [ "$code" = "$EXPECT" ]; then
    echo "   $name：$code 正常"
  else
    echo "   $name：$code 异常（期望 $EXPECT）" >&2
    FAILED=1
  fi
}
EXPECT=200
check "HTTPS 登录页"     --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/login"
check "HTTPS 退费首页"   --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/refund/"
check "HTTPS 退费接口"   --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/refund/api/auth/wechat/status"
check "旧入口 5050 保留" "http://127.0.0.1:5050/refund/"
EXPECT=301
check "HTTP 80 跳转"     -H "Host: $DOMAIN" "http://127.0.0.1/login"

if [ "$FAILED" -ne 0 ]; then
  echo "健康检查未通过，可执行 ./deploy/switch-https.sh --revert 回滚" >&2
  exit 1
fi

echo "========== 切换完成 $(date) =========="
echo "正式入口：https://$DOMAIN/ 与 https://$DOMAIN/refund/"
echo "兼容入口：http://101.200.231.62:5050/refund/（旧签字链接继续可用）"
echo "请从公网验证：curl -I https://$DOMAIN/ ；微信授权域名填 $DOMAIN"
echo "回滚：./deploy/switch-https.sh --revert（备份 $SNAP）"
