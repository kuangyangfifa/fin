#!/usr/bin/env bash
# fin-remark 每日备份（适配既有 systemd 站点，WAL 安全）
#
# 为什么不能直接 cp finance_web.db：应用开启 SQLite WAL 后，最新提交可能仍在
# -wal 文件中，直接拷贝 .db 会拿到不完整/落后的数据。这里用 sqlite3 .backup
# （等价于官方 Online Backup API），由 SQLite 自己合并 WAL 后导出一致性快照。
#
# 建议 crontab（每天 02:10）：
#   10 2 * * * /home/fin/fin/deploy/backup.sh >> /home/fin/logs/backup.log 2>&1
#
# 覆盖：finance_web.db 一致性快照、退费单据/账号/附件、Nginx 与 systemd 配置、代码版本
# 不覆盖：.env（含 AI 密钥与 SECRET_KEY，请另行离线保管）

set -euo pipefail

APP_DIR="${APP_DIR:-/home/fin/fin}"
DB_FILE="${DB_FILE:-$APP_DIR/instance/finance_web.db}"
REFUND_DATA="${REFUND_DATA:-/home/fin/refund-data}"
BACKUP_DIR="${BACKUP_DIR:-/home/fin/backups/daily}"
KEEP_DAYS="${KEEP_DAYS:-30}"
SQLITE3="${SQLITE3:-/root/miniconda3/bin/sqlite3}"

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/fin-backup-$STAMP.tar.gz"
TMP="$(mktemp -d /tmp/fin-backup.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$BACKUP_DIR"
echo "[$(date '+%F %T')] 开始备份"

# 1. SQLite 一致性快照（WAL 安全）
if [ -x "$SQLITE3" ]; then
  "$SQLITE3" "$DB_FILE" ".backup '$TMP/finance_web.db'"
else
  python3 - "$DB_FILE" "$TMP/finance_web.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PY
fi
echo "   数据库快照：$("$SQLITE3" "$TMP/finance_web.db" \
  "select 'users='||(select count(*) from users)||' accounts='||(select count(*) from accounts)||' transactions='||(select count(*) from transactions);" 2>/dev/null || echo 已导出)"

# 2. 退费模块数据（单据、账号、会话、附件、配置）
if [ -d "$REFUND_DATA" ]; then
  tar -czf "$TMP/refund-data.tar.gz" -C "$REFUND_DATA" .
  echo "   退费数据：已归档"
fi

# 3. 运行配置与代码版本（便于整机重建）
mkdir -p "$TMP/conf"
[ -f /etc/nginx/conf.d/finance.conf ]            && cp -a /etc/nginx/conf.d/finance.conf "$TMP/conf/"
[ -f /etc/systemd/system/fin.service ]           && cp -a /etc/systemd/system/fin.service "$TMP/conf/"
[ -f /etc/systemd/system/fin-refund.service ]    && cp -a /etc/systemd/system/fin-refund.service "$TMP/conf/"
(cd "$APP_DIR" && git rev-parse HEAD > "$TMP/conf/git-head.txt" 2>/dev/null) || true

tar -czf "$DEST" -C "$TMP" .
chmod 600 "$DEST"
echo "   备份文件：$DEST ($(du -h "$DEST" | cut -f1))"

# 4. 清理过期备份
find "$BACKUP_DIR" -name "fin-backup-*.tar.gz" -mtime "+$KEEP_DAYS" -delete
echo "[$(date '+%F %T')] 备份完成，保留最近 ${KEEP_DAYS} 天"
