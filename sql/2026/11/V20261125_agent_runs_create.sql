-- ============================================================================
-- agent_runs 运行记录表（2026-11-25）
--
-- 背景：Agent / Plan 运行目前只有进程内 run_registry，进程重启即丢；
--       需要一条持久化的运行记录，支撑「运行列表 / 运行详情 / 重启恢复」。
--
-- 变更：新建 agent_runs + 主键 + 3 个索引 + 全部表/字段注释。
--
-- 状态机：queued → running → succeeded / failed / cancelled / interrupted
--                     ↘ paused → running（HITL 审批恢复）
--
-- 幂等：IF NOT EXISTS / COMMENT 覆盖写，可重复执行。
--
-- 适用：PostgreSQL。SQLite 开发库由 SQLModel.metadata.create_all 建表。
-- ============================================================================


CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      VARCHAR(64) NOT NULL,
    session_id  VARCHAR(64),
    tenant_id   VARCHAR(36) NOT NULL,
    user_id     VARCHAR(36) NOT NULL,
    mode        VARCHAR(16) NOT NULL DEFAULT 'single',
    status      VARCHAR(16) NOT NULL DEFAULT 'queued',
    input       TEXT        NOT NULL DEFAULT '{}',
    output      TEXT,
    error       TEXT,
    token_usage TEXT        NOT NULL DEFAULT '{}',
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_agent_runs PRIMARY KEY (run_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_tenant_created
    ON agent_runs (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS ix_agent_runs_session
    ON agent_runs (session_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_user_status
    ON agent_runs (user_id, status);

COMMENT ON TABLE  agent_runs             IS 'Agent 运行记录表：每次 run 一条，记录状态机、耗时与 token 消耗，重启恢复依据';
COMMENT ON COLUMN agent_runs.run_id      IS '运行ID（主键，字符串，API 路径参数与审计 target 使用）';
COMMENT ON COLUMN agent_runs.session_id  IS '关联会话ID（可空：脱离会话的定时/渠道任务为空）';
COMMENT ON COLUMN agent_runs.tenant_id   IS '所属租户ID，查询强制隔离';
COMMENT ON COLUMN agent_runs.user_id     IS '发起人用户ID';
COMMENT ON COLUMN agent_runs.mode        IS '运行模式：single 单 Agent / coordinator 多 Agent 编排';
COMMENT ON COLUMN agent_runs.status      IS '状态：queued / running / paused / succeeded / failed / cancelled / interrupted';
COMMENT ON COLUMN agent_runs.input       IS '运行入参（JSON 字符串）：goal、模式参数、幂等键等';
COMMENT ON COLUMN agent_runs.output      IS '运行产出的最终回答或计划结果（可空）';
COMMENT ON COLUMN agent_runs.error       IS '失败时的错误摘要（可空，完整栈在日志）';
COMMENT ON COLUMN agent_runs.token_usage IS 'Token 用量（JSON 字符串）：input / output / cached / model';
COMMENT ON COLUMN agent_runs.started_at  IS '开始执行时间（UTC，可空）';
COMMENT ON COLUMN agent_runs.finished_at IS '结束时间（UTC，可空；running 状态为空）';
COMMENT ON COLUMN agent_runs.created_at  IS '创建时间（UTC）';
COMMENT ON COLUMN agent_runs.updated_at  IS '最后更新时间（UTC，状态流转时刷新）';


-- ---------------------------------------------------------------------------
-- 核对：表存在、索引=4（含主键）、字段注释=14
-- ---------------------------------------------------------------------------
SELECT COUNT(*) AS table_exists
FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'agent_runs';

SELECT COUNT(*) AS index_count
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'agent_runs';

SELECT COUNT(*) AS column_comments
FROM pg_description d
JOIN pg_class c ON c.oid = d.objoid
WHERE c.relname = 'agent_runs' AND d.objsubid > 0;


-- ============================================================================
-- 回退（会丢失运行记录，仅在确认后手动执行）
-- ============================================================================
-- DROP TABLE IF EXISTS agent_runs CASCADE;


-- ---------------------------------------------------------------------------
-- 执行记录
-- 时间：2026-11-25
-- 环境：Docker harness-pg（postgres:16，localhost:5433/harness）
-- 结果：成功。新增 1 表 / 3 数据索引 / 14 条字段注释。
-- ---------------------------------------------------------------------------
