#!/usr/bin/env bash
# 创建独立的测试库 finance_test（可重复执行）
# 用法：sudo bash scripts/create_test_db.sh
set -uo pipefail

CD=/opt/finance-ai
PW=$(grep '^PGPASSWORD=' $CD/.env | cut -d= -f2 | tr -d '\r')

if [ -z "$PW" ]; then
    echo "❌ 读不到 .env 里的 PGPASSWORD"
    exit 1
fi

echo "1) 重建测试库 finance_test"
sudo -u postgres psql -q -c "DROP DATABASE IF EXISTS finance_test;" 2>/dev/null
sudo -u postgres psql -q -c "CREATE DATABASE finance_test OWNER finance;" 2>/dev/null

echo "2) 导入表结构（以 finance 身份，保证表归 finance 所有）"
PGPASSWORD="$PW" psql -h 127.0.0.1 -U finance -d finance_test -q -f $CD/schema.sql

echo "3) 验证"
PGPASSWORD="$PW" psql -h 127.0.0.1 -U finance -d finance_test -tAc \
  "SELECT '  表: ' || string_agg(tablename, ', ' ORDER BY tablename) FROM pg_tables WHERE schemaname='public';"

echo "✅ 测试库就绪：finance_test"
