#!/usr/bin/env bash
# 备案生效后：签发 Let's Encrypt 证书并配置自动续期
#
# 前置（必须先满足，否则 HTTP-01 验证必然失败）：
#   从公网执行 curl -I http://lexueisland.site/ 不再返回 403 ICP 拦截。
#   服务器内部 curl 域名会走内网直通，不能用来判断备案是否生效。
#
# 用法：
#   CERTBOT_EMAIL='you@example.com' ./deploy/issue-cert.sh
#   （不提供邮箱也可以，会使用 --register-unsafely-without-email，
#     但收不到证书到期提醒，建议填写）
#
# 验证方式：webroot。Nginx 默认 80 站点的 root 为 /usr/share/nginx/html，
# 切换 HTTPS 后 80 配置仍保留 /.well-known/acme-challenge/ 例外，续期不受影响。

set -euo pipefail

DOMAIN="${DOMAIN:-lexueisland.site}"
WEBROOT="${WEBROOT:-/usr/share/nginx/html}"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"

echo "========== 签发证书 $DOMAIN $(date) =========="

# 1. 确认 80 端口由 Nginx 提供、webroot 可写
systemctl is-active nginx >/dev/null || { echo "错误：Nginx 未运行"; exit 1; }
mkdir -p "$WEBROOT/.well-known/acme-challenge"
[ -w "$WEBROOT/.well-known/acme-challenge" ] || { echo "错误：$WEBROOT 不可写"; exit 1; }

# 2. 安装 certbot（Alibaba Cloud Linux 3 的 EPEL 源提供 1.22）
if ! command -v certbot >/dev/null; then
  echo "[1/3] 安装 certbot..."
  dnf install -y certbot >/dev/null
else
  echo "[1/3] certbot 已安装：$(certbot --version 2>&1)"
fi

# 3. 签发（已有证书且未到期时 certbot 会自行跳过）
echo "[2/3] 通过 HTTP-01 签发证书..."
if [ -f "$CERT_DIR/fullchain.pem" ]; then
  echo "   证书已存在，跳过签发：$CERT_DIR/fullchain.pem"
else
  EMAIL_ARGS=(--register-unsafely-without-email)
  if [ -n "$CERTBOT_EMAIL" ]; then
    EMAIL_ARGS=(--email "$CERTBOT_EMAIL")
  fi
  if ! certbot certonly \
        --webroot -w "$WEBROOT" \
        -d "$DOMAIN" \
        --cert-name "$DOMAIN" \
        --non-interactive --agree-tos \
        "${EMAIL_ARGS[@]}"; then
    echo "" >&2
    echo "签发失败。最常见原因：备案拦截尚未解除，公网访问" >&2
    echo "  http://$DOMAIN/.well-known/acme-challenge/... 返回 403。" >&2
    echo "请从本机（非服务器）执行 curl -I http://$DOMAIN/ 确认后再重试。" >&2
    exit 1
  fi
fi

[ -f "$CERT_DIR/fullchain.pem" ] || { echo "错误：证书文件未生成"; exit 1; }
echo "   证书：$CERT_DIR/fullchain.pem"
echo "   私钥：$CERT_DIR/privkey.pem"

# 4. 自动续期（每天 03:25，仅在实际续期成功时 reload Nginx）
echo "[3/3] 配置自动续期..."
systemctl disable --now certbot-renew.timer >/dev/null 2>&1 || true
mkdir -p /home/fin/logs
CRON_LINE="25 3 * * * /usr/bin/certbot renew --quiet --deploy-hook '/usr/bin/systemctl reload nginx' >> /home/fin/logs/certbot-renew.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'certbot renew' || true; echo "$CRON_LINE" ) | crontab -
crontab -l | grep -E 'certbot|backup.sh'

echo "========== 证书就绪 $(date) =========="
echo "下一步：./deploy/switch-https.sh"
