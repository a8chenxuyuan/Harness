-- ============================================================================
-- sessions 扩展：summary / last_message_at（2026-11-25）
--
-- 背景：会话列表需要显示「最后活跃时间」，上下文压缩需要会话级摘要缓存。
--       message_count 与 status 已存在于 20261125 基线脚本，本次不重复添加。
--
-- 变更：sessions 新增 2 列 + 对应字段注释。
--       summary           会话摘要（超过阈值后由内核写入，供上下文装配复用）
--       last_message_at   最后一条消息时间（消息写入时刷新，列表排序用）
--
-- 幂等：ADD COLUMN IF NOT EXISTS / COMMENT 覆盖写，可重复执行。
--
-- 适用：PostgreSQL。SQLite 开发库由 SQLModel.metadata.create_all 建表，
--       已有开发库如缺列需手工 ALTER（SQLite 不支持 IF NOT EXISTS 加列）。
-- ============================================================================


ALTER TABLE sessions ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ;

COMMENT ON COLUMN sessions.summary         IS '会话摘要：超阈值后由内核压缩写入，供后续上下文装配与列表预览复用';
COMMENT ON COLUMN sessions.last_message_at IS '最后一条消息时间（UTC，可空）；消息写入时刷新，会话列表按它倒序';


CREATE INDEX IF NOT EXISTS ix_sessions_tenant_user_last_message
    ON sessions (tenant_id, user_id, last_message_at DESC);


-- ---------------------------------------------------------------------------
-- 核对：2 列存在、1 索引存在
-- ---------------------------------------------------------------------------
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'sessions'
  AND column_name IN ('summary', 'last_message_at');

SELECT COUNT(*) AS index_exists
FROM pg_indexes
WHERE schemaname = 'public' AND indexname = 'ix_sessions_tenant_user_last_message';


-- ============================================================================
-- 回退（会丢失摘要与排序字段，仅在确认后手动执行）
-- ============================================================================
-- DROP INDEX IF EXISTS ix_sessions_tenant_user_last_message;
-- ALTER TABLE sessions DROP COLUMN IF EXISTS last_message_at;
-- ALTER TABLE sessions DROP COLUMN IF EXISTS summary;


-- ---------------------------------------------------------------------------
-- 执行记录
-- 时间：2026-11-25
-- 环境：Docker harness-pg（postgres:16，localhost:5433/harness）
-- 结果：成功。sessions 新增 2 列 / 1 索引 / 2 条字段注释。
-- ---------------------------------------------------------------------------
