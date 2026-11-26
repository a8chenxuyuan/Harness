-- ============================================================================
-- session_messages 会话消息表（2026-11-25）
--
-- 背景：sessions 只存元数据、session_entries 是内核事件流水（checkpoint），
--       前端工作台需要一份「可分页、可检索、可分支」的对话消息表。
--
-- 变更：新建 session_messages + 主键 + 2 个索引 + 全部表/字段注释。
--
-- 设计：append-only。编辑/重生成不覆盖历史，用 parent_id 指向被修改的消息
--       形成分支；parts 为 JSON 数组字符串，元素类型：
--         {"type":"text","text":"..."} /
--         {"type":"tool_call","name":"...","arguments":{...}} /
--         {"type":"tool_result","tool_call_id":"...","content":"..."} /
--         {"type":"thinking","text":"..."}
--       PG 侧列类型为 JSONB，应用层实体按 JSON 列表读写（SQLite 侧为 JSON 文本），
--       需要 JSON 检索时在 PG 上直接对 parts 建表达式索引即可。
--
-- 幂等：IF NOT EXISTS / COMMENT 覆盖写，可重复执行。
--
-- 适用：PostgreSQL。SQLite 开发库由 SQLModel.metadata.create_all 建表。
-- ============================================================================


CREATE TABLE IF NOT EXISTS session_messages (
    id         VARCHAR(64)  NOT NULL,
    session_id VARCHAR(64)  NOT NULL,
    tenant_id  VARCHAR(36)  NOT NULL,
    user_id    VARCHAR(36)  NOT NULL,
    role       VARCHAR(16)  NOT NULL,
    parts      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    text       TEXT         NOT NULL DEFAULT '',
    seq        BIGINT       NOT NULL,
    parent_id  VARCHAR(64),
    status     VARCHAR(16)  NOT NULL DEFAULT 'completed',
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ  NOT NULL,
    CONSTRAINT pk_session_messages PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_session_messages_session_seq
    ON session_messages (session_id, seq);
CREATE INDEX IF NOT EXISTS ix_session_messages_tenant_created
    ON session_messages (tenant_id, created_at);

COMMENT ON TABLE  session_messages            IS '会话消息表：append-only 保存对话消息，编辑/重生成通过 parent_id 形成分支';
COMMENT ON COLUMN session_messages.id         IS '消息ID（主键，字符串UUID，SSE 事件 id 也用它）';
COMMENT ON COLUMN session_messages.session_id IS '所属会话ID，外键语义关联 sessions.session_id';
COMMENT ON COLUMN session_messages.tenant_id  IS '所属租户ID，所有查询强制带上，用于租户隔离';
COMMENT ON COLUMN session_messages.user_id    IS '消息产生者：user 消息为用户ID，assistant/tool 消息为运行主体标识';
COMMENT ON COLUMN session_messages.role       IS '消息角色：user 用户 / assistant 助手 / system 系统 / tool 工具结果';
COMMENT ON COLUMN session_messages.parts      IS '内容块数组（JSON）：text / tool_call / tool_result / thinking';
COMMENT ON COLUMN session_messages.text       IS '纯文本冗余（由 parts 中 text 拼接），用于搜索与列表预览';
COMMENT ON COLUMN session_messages.seq        IS '会话内单调递增序号，分页与回放游标，不用 offset';
COMMENT ON COLUMN session_messages.parent_id  IS '分支来源消息ID（编辑/重生成时指向被替代的消息，可空）';
COMMENT ON COLUMN session_messages.status     IS '消息状态：streaming 生成中 / completed 完成 / failed 失败';
COMMENT ON COLUMN session_messages.deleted_at IS '软删时间（UTC，可空）；归档任务按保留策略物理清理';
COMMENT ON COLUMN session_messages.created_at IS '创建时间（UTC）';


-- ---------------------------------------------------------------------------
-- 核对：表存在、索引=3（含主键）、字段注释=12
-- ---------------------------------------------------------------------------
SELECT COUNT(*) AS table_exists
FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'session_messages';

SELECT COUNT(*) AS index_count
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'session_messages';

SELECT COUNT(*) AS column_comments
FROM pg_description d
JOIN pg_class c ON c.oid = d.objoid
WHERE c.relname = 'session_messages' AND d.objsubid > 0;


-- ============================================================================
-- 回退（会丢失消息数据，仅在确认后手动执行）
-- ============================================================================
-- DROP TABLE IF EXISTS session_messages CASCADE;


-- ---------------------------------------------------------------------------
-- 执行记录
-- 时间：2026-11-25
-- 环境：Docker harness-pg（postgres:16，localhost:5433/harness）
-- 结果：成功。新增 1 表 / 2 数据索引 / 12 条字段注释。
-- ---------------------------------------------------------------------------
