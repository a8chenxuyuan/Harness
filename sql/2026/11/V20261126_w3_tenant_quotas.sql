-- ============================================================================
-- 租户配额与按天用量（W3-PLAT-01，2026-11-26）
--
-- 背景：多租户场景需要限制单租户的并发运行、当日消息数与 token 消耗，
--       防止单个租户挤占全部模型配额。
--
-- 表：
--   tenant_quotas       每租户一行，缺省值即免费版额度
--   tenant_usage_daily  按 (tenant_id, usage_date) 累加，UTC 自然日
--
-- 检查时机：/agents/run 与 /agents/run/stream 开跑前；超限返回 429。
-- 并发数不落 usage 表，实时统计 agent_runs 中 queued / running 的条数。
--
-- 幂等：CREATE TABLE / INDEX IF NOT EXISTS + COMMENT 覆盖写。
--
-- 适用：PostgreSQL。SQLite 开发库由 SQLModel.metadata.create_all 建表。
-- ============================================================================

CREATE TABLE IF NOT EXISTS tenant_quotas (
    tenant_id           VARCHAR(36) NOT NULL,
    max_concurrent_runs INT         NOT NULL DEFAULT 4,
    max_daily_messages  INT         NOT NULL DEFAULT 2000,
    max_daily_tokens    BIGINT      NOT NULL DEFAULT 2000000,
    updated_at          TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_tenant_quotas PRIMARY KEY (tenant_id)
);

CREATE TABLE IF NOT EXISTS tenant_usage_daily (
    tenant_id    VARCHAR(36) NOT NULL,
    usage_date   VARCHAR(10) NOT NULL,
    runs_started INT         NOT NULL DEFAULT 0,
    messages     INT         NOT NULL DEFAULT 0,
    tokens       BIGINT      NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_tenant_usage_daily PRIMARY KEY (tenant_id, usage_date)
);
CREATE INDEX IF NOT EXISTS ix_tenant_usage_daily_date
    ON tenant_usage_daily (usage_date);

COMMENT ON TABLE  tenant_quotas                     IS '租户配额表：并发运行 / 当日消息 / 当日 token 上限';
COMMENT ON COLUMN tenant_quotas.tenant_id           IS '租户ID（主键，与 tenants.id 对应）';
COMMENT ON COLUMN tenant_quotas.max_concurrent_runs IS '最大并发运行数（统计 agent_runs 中 queued/running）';
COMMENT ON COLUMN tenant_quotas.max_daily_messages  IS '每日消息条数上限（用户 + 助手各计 1 条）';
COMMENT ON COLUMN tenant_quotas.max_daily_tokens    IS '每日 token 用量上限';
COMMENT ON COLUMN tenant_quotas.updated_at          IS '最后更新时间（UTC）';

COMMENT ON TABLE  tenant_usage_daily              IS '租户按天用量表：run 开始 / 消息 / token 累加';
COMMENT ON COLUMN tenant_usage_daily.tenant_id    IS '租户ID（复合主键之一）';
COMMENT ON COLUMN tenant_usage_daily.usage_date   IS 'UTC 日期 YYYY-MM-DD（复合主键之一）';
COMMENT ON COLUMN tenant_usage_daily.runs_started IS '当日启动的运行次数';
COMMENT ON COLUMN tenant_usage_daily.messages     IS '当日落库的消息条数';
COMMENT ON COLUMN tenant_usage_daily.tokens       IS '当日 token 消耗';
COMMENT ON COLUMN tenant_usage_daily.updated_at   IS '最后更新时间（UTC）';


-- ---------------------------------------------------------------------------
-- 核对：两张表存在
-- ---------------------------------------------------------------------------
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('tenant_quotas', 'tenant_usage_daily')
ORDER BY table_name;


-- ============================================================================
-- 回退（会丢失配额与用量记录）
-- ============================================================================
-- DROP TABLE IF EXISTS tenant_usage_daily CASCADE;
-- DROP TABLE IF EXISTS tenant_quotas CASCADE;


-- ---------------------------------------------------------------------------
-- 执行记录
-- 时间：2026-11-26
-- 环境：Docker harness-pg（postgres:16，localhost:5433/harness）
-- 结果：待执行（本地 SQLite 由 create_all 建表）。
-- ---------------------------------------------------------------------------
