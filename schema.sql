-- ==========================================
-- 财务 AI 系统 · 数据库初始化脚本
-- 适用：PostgreSQL 14+
-- 用法：sudo -u postgres psql -d finance -f schema.sql
-- ==========================================

-- ---------- 用户表 ----------
CREATE TABLE IF NOT EXISTS users (
    username   text PRIMARY KEY,
    password   text NOT NULL,                 -- 目前是明文，后续建议换成 bcrypt 哈希
    role       text DEFAULT '普通用户',
    created_at timestamptz DEFAULT now()
);

-- ---------- 发票表 ----------
CREATE TABLE IF NOT EXISTS invoices (
    id           bigserial PRIMARY KEY,
    "发票号码"   text UNIQUE,                  -- 唯一，用于重复上传时去重
    "开票日期"   date,
    "购买方名称" text,
    "销售方名称" text,
    "价税合计"   numeric(14, 2),
    "发票类型"   text,
    "文件名"     text,
    created_at   timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invoices_buyer  ON invoices ("购买方名称");
CREATE INDEX IF NOT EXISTS idx_invoices_seller ON invoices ("销售方名称");
CREATE INDEX IF NOT EXISTS idx_invoices_date   ON invoices ("开票日期");

-- ---------- 流水表 ----------
CREATE TABLE IF NOT EXISTS transactions (
    id         bigserial PRIMARY KEY,
    "交易备注" text,
    "金额"     numeric(14, 2),
    "AI分类"   text,
    created_at timestamptz DEFAULT now()
);

-- ---------- 给应用用的数据库账号 ----------
-- 首次部署时手动执行（把密码换掉）：
--   CREATE USER finance WITH PASSWORD '改成一个强密码';
--   GRANT ALL PRIVILEGES ON DATABASE finance TO finance;
--   \c finance
--   GRANT ALL ON SCHEMA public TO finance;
--   GRANT ALL ON ALL TABLES IN SCHEMA public TO finance;
--   GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO finance;


-- ==========================================
-- 对话记忆（网页与飞书共用）
-- ==========================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_key TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    channel TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_key_id ON chat_messages (conversation_key, id);

-- 飞书身份绑定：绑定后网页和飞书共用同一段对话
ALTER TABLE users ADD COLUMN IF NOT EXISTS feishu_open_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_feishu_open_id
    ON users (feishu_open_id) WHERE feishu_open_id IS NOT NULL;
