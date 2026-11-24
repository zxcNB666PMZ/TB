#!/usr/bin/env bash
# 财务系统状态总览：bash /opt/finance-ai/status.sh
CD=/opt/finance-ai

# 只在真正的终端里输出颜色；通过 ssh 执行命令时（非 tty）不输出转义符
if [ -t 1 ]; then
  G='\033[0;32m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'
else
  G=''; R=''; B=''; N=''
fi

ok()      { echo -e "  ${G}✅ $1${N}"; }
bad()     { echo -e "  ${R}❌ $1${N}"; }
section() { echo -e "\n${B}===== $1 =====${N}"; }

section "服务状态"
for s in finance-ai finance-bot; do
  st=$(systemctl is-active "$s" 2>/dev/null)
  if [ "$st" = "active" ]; then ok "$s  ($st)"; else bad "$s  ($st)"; fi
done
tst=$(systemctl is-active finance-healthcheck.timer 2>/dev/null)
if [ "$tst" = "active" ]; then ok "健康检查定时器  ($tst)"; else bad "健康检查定时器  ($tst)"; fi

section "下次健康检查"
systemctl list-timers --all 2>/dev/null | grep -E 'NEXT|finance-healthcheck' | sed 's/  */ /g' \
  || echo "  未找到定时器"

section "最近检查记录"
journalctl -u finance-healthcheck -n 6 --no-pager 2>/dev/null \
  | sed -E 's/^.*iZ[A-Za-z0-9]+ //' || echo "  无记录"

section "数据库"
PW=$(grep '^PGPASSWORD=' "$CD/.env" | cut -d= -f2 | tr -d '\r')
PGPASSWORD="$PW" psql -h 127.0.0.1 -U finance -d finance -tAc \
  "SELECT '  ' || count(*) || ' 张发票，合计 ' || coalesce(sum(\"价税合计\"),0) || ' 元' FROM invoices;" 2>/dev/null \
  || echo "  查询失败（检查 .env 里的 PG 配置）"

section "资源"
free -h | head -2 | sed 's/^/  /'
df -h / | tail -1 | sed 's/^/  /'

section "网页"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8501/_stcore/health)
if [ "$code" = "200" ]; then ok "http://8.140.220.172:8501  (HTTP $code)"; else bad "网页无响应 (HTTP $code)"; fi
echo
