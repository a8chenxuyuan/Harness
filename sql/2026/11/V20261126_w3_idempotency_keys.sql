-- ============================================================================
-- idempotency_keys 幂等键表（W3-KERN-02，2026-11-26）
--
-- 背景：客户端 / 网关在网络抖动后会重试 POST /agents/run 与 /run/stream。
--       没有幂等键时同一个目标会被重复执行、重复计费、重复写会话。
--
-- 语义：
--   (tenant_id, scope, key) 唯一；request_hash 记录首次请求入参。
--   - 同 key + 同 hash + succeeded：同步接口回放 response_json
--   - 同 key + 同 hash + in_progress：409（流式接口带 run_id）
--   - 同 key + 不同 hash：409，避免把旧结果错配给新请求
--   - 服务重启：in_progress 记录由启动恢复逻辑清空，允许重试
--
-- 幂等：CREATE TABLE / INDEX IF NOT EXISTS + COMMENT 覆盖写，可重复执行。
--
-- 适用：PostgreSQL。SQLite 开发库由 SQLModel.metadata.create_all 建表。
-- ============================================================================

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id            VARCHAR(36)  NOT NULL,
    tenant_id     VARCHAR(36)  NOT NULL,
    scope         VARCHAR(32)  NOT NULL,
    key           VARCHAR(128) NOT NULL,
    request_hash  VARCHAR(64)  NOT NULL,
    status        VARCHAR(16)  NOT NULL DEFAULT 'in_progress',
    run_id        VARCHAR(64),
    response_json TEXT,
    created_at    TIMESTAMPTZ  NOT NULL,
    updated_at    TIMESTAMPTZ  NOT NULL,
    CONSTRAINT pk_idempotency_keys PRIMARY KEY (id),
    CONSTRAINT uq_idempotency_tenant_scope_key
        UNIQUE (tenant_id, scope, key)
);
CREATE INDEX IF NOT EXISTS ix_idempotency_keys_tenant
    ON idempotency_keys (tenant_id);

COMMENT ON TABLE  idempotency_keys              IS '幂等键表：同租户 + 场景 + 键唯一，防网络重试导致重复执行';
COMMENT ON COLUMN idempotency_keys.id           IS '记录ID（uuid）';
COMMENT ON COLUMN idempotency_keys.tenant_id    IS '所属租户ID，隔离维度之一';
COMMENT ON COLUMN idempotency_keys.scope        IS '场景：agent.run 同步运行 / agent.run.stream 流式运行';
COMMENT ON COLUMN idempotency_keys.key          IS '客户端 Idempotency-Key（≤128）';
COMMENT ON COLUMN idempotency_keys.request_hash IS '首次请求体 SHA-256，用于识别同键不同体';
COMMENT ON COLUMN idempotency_keys.status       IS '状态：in_progress 处理中 / succeeded 已完成';
COMMENT ON COLUMN idempotency_keys.run_id       IS '关联运行ID（流式接口 409 时返回给前端轮询）';
COMMENT ON COLUMN idempotency_keys.response_json IS '成功响应缓存（仅同步接口回放使用）';
COMMENT ON COLUMN idempotency_keys.created_at   IS '创建时间（UTC）';
COMMENT ON COLUMN idempotency_keys.updated_at   IS '最后更新时间（UTC）';


-- ---------------------------------------------------------------------------
-- 核对：表 + 唯一约束
-- ---------------------------------------------------------------------------
SELECT COUNT(*) AS table_exists
FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'idempotency_keys';

SELECT conname
FROM pg_constraint
WHERE conname = 'uq_idempotency_tenant_scope_key';


-- ============================================================================
-- 回退（会丢失幂等记录）
-- ============================================================================
-- DROP TABLE IF EXISTS idempotency_keys CASCADE;


-- ---------------------------------------------------------------------------
-- 执行记录
-- 时间：2026-11-26
-- 环境：Docker harness-pg（postgres:16，localhost:5433/harness）
-- 结果：待执行（本地 SQLite 由 create_all 建表）。
-- ---------------------------------------------------------------------------
