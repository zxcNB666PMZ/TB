#!/usr/bin/env bash
# 财务数据库自动备份：pg_dump → gzip → 保留 7 天 → 飞书通知
set -uo pipefail

CD=/opt/finance-ai
BK=/opt/finance-backup
KEEP_DAYS=7

mkdir -p "$BK"
PW=$(grep '^PGPASSWORD=' "$CD/.env" | cut -d= -f2 | tr -d '\r')
CHAT=$(grep '^ALERT_CHAT_ID=' "$CD/.env" | cut -d= -f2 | tr -d '\r')

STAMP=$(date +%Y%m%d_%H%M)
OUT="$BK/finance_$STAMP.sql.gz"
ERRLOG=$(mktemp)

notify() {
    [ -n "${CHAT:-}" ] || return 0
    "$CD/.venv/bin/python" "$CD/feishu_notify.py" "$CHAT" "$1" >/dev/null 2>&1 || true
}

# ---------- 备份前先记录业务基线 ----------
BASE=$(PGPASSWORD="$PW" psql -h 127.0.0.1 -U finance -d finance -tAc \
  "SELECT count(*) || ' 张发票 / ' || round(coalesce(sum(\"价税合计\"),0)::numeric,2) || ' 元' FROM invoices;" \
  2>>"$ERRLOG" | tr -d ' ')

# ---------- 执行备份 ----------
set -o pipefail
PGPASSWORD="$PW" pg_dump -h 127.0.0.1 -U finance -d finance \
  --no-owner --no-acl --clean --if-exists 2>"$ERRLOG" | gzip -9 > "$OUT"
RC=$?

# ---------- 校验 ----------
OK=1
[ $RC -eq 0 ] || OK=0
gzip -t "$OUT" 2>/dev/null || OK=0
SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
[ "$SIZE" -gt 500 ] || OK=0
grep -q 'CREATE TABLE' <(zcat "$OUT" 2>/dev/null) || OK=0

if [ $OK -eq 1 ]; then
    # 清理过期备份
    DELETED=$(find "$BK" -name 'finance_*.sql.gz' -mtime +$KEEP_DAYS -print -delete | wc -l)
    COUNT=$(ls -1 "$BK"/finance_*.sql.gz 2>/dev/null | wc -l)
    TOTAL=$(du -sh "$BK" 2>/dev/null | cut -f1)
    echo "OK  $OUT  ($SIZE bytes)  基线: $BASE  现有备份 $COUNT 份 / $TOTAL  清理 $DELETED 份"
    notify "✅ 数据库备份成功
时间：$STAMP
基线：$BASE
文件：finance_$STAMP.sql.gz（$(numfmt --to=iec $SIZE 2>/dev/null || echo ${SIZE}B)）
现存 $COUNT 份备份，共 $TOTAL"
    exit 0
else
    REASON=$(tail -3 "$ERRLOG" | tr '\n' ' ')
    echo "FAIL $OUT  size=$SIZE  rc=$RC  $REASON"
    notify "🚨 数据库备份失败
时间：$STAMP
原因：$REASON
请登录服务器检查：journalctl -u finance-backup"
    exit 1
fi