-- ============================================================================
-- harness 平台库全量初始化（2026-11-25）
--
-- 背景：重置 PG / SQLite 后，需要一份可复核的全量建表脚本作为留痕基线，
--       且表与字段必须带注释，便于 Navicat / psql 直接读懂结构。
--
-- 变更：新建 7 张表 + 全部索引 + 1 个唯一约束 + 63 条表/字段注释：
--       tenants / users / sessions / audit_logs / memories /
--       plans / session_entries
--
-- 影响：仅初始化空库。已有数据的环境请勿直接执行本文件，
--       增量改动请新增 sql/<yyyy>/<MM>/V<yyyyMMdd>_<表>_<动作>.sql。
--
-- 幂等：全部使用 IF NOT EXISTS / COMMENT 覆盖写；
--       重复执行不会报错，也不会重复建对象。
--
-- 执行顺序：本文件是全量基线，空库首次部署执行一次即可；
--       后续增量脚本按 sql/<yyyy>/<MM>/ 下文件名的日期先后执行。
--
-- 适用：PostgreSQL。SQLite 不支持 COMMENT 语法，本地开发库由应用启动时
--       通过 SQLModel.metadata.create_all 自动建表（无注释，仅结构）。
--       约束变更在 SQLite 上需重建表，正式环境请统一用 PostgreSQL。
--
-- 种子数据：不在本文件内（bcrypt 哈希需运行时计算），
--       执行 `python -c "import asyncio; from harness.platform.db.seed import seed_default; asyncio.run(seed_default())"`。
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 1) tenants 租户表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id         VARCHAR(36)  NOT NULL,
    name       VARCHAR(128) NOT NULL,
    plan       VARCHAR(32)  NOT NULL DEFAULT 'free',
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP    NOT NULL,
    CONSTRAINT pk_tenants PRIMARY KEY (id)
);
COMMENT ON TABLE  tenants            IS '租户表：一个租户代表一个独立组织/客户，所有业务数据按 tenant_id 隔离';
COMMENT ON COLUMN tenants.id         IS '租户ID（主键，字符串UUID；开发环境固定 dev-tenant）';
COMMENT ON COLUMN tenants.name       IS '租户名称（展示用，如 Dev Tenant）';
COMMENT ON COLUMN tenants.plan       IS '订阅套餐：free / pro / enterprise（当前未做计费，仅占位）';
COMMENT ON COLUMN tenants.is_active  IS '是否启用：true 启用；false 停用后该租户下所有用户不可登录';
COMMENT ON COLUMN tenants.created_at IS '创建时间（UTC）';


-- ---------------------------------------------------------------------------
-- 2) users 用户表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(36)  NOT NULL,
    tenant_id       VARCHAR(36)  NOT NULL,
    username        VARCHAR(64)  NOT NULL,
    email           VARCHAR(256) NOT NULL DEFAULT '',
    hashed_password VARCHAR(256) NOT NULL,
    role            VARCHAR(16)  NOT NULL DEFAULT 'member',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL,
    updated_at      TIMESTAMP    NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT uq_users_tenant_username UNIQUE (tenant_id, username)
);
CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users (tenant_id);
CREATE INDEX IF NOT EXISTS ix_users_username  ON users (username);
COMMENT ON TABLE  users                 IS '用户表：归属某个租户，role 决定权限（owner 所有者 / admin 管理员 / member 普通成员）';
COMMENT ON COLUMN users.id              IS '用户ID（主键，字符串UUID）';
COMMENT ON COLUMN users.tenant_id       IS '所属租户ID，外键关联 tenants.id，租户隔离的核心字段';
COMMENT ON COLUMN users.username        IS '登录用户名，租户内唯一（UNIQUE(tenant_id, username)）';
COMMENT ON COLUMN users.email           IS '邮箱，全局唯一（UNIQUE(email)）';
COMMENT ON COLUMN users.hashed_password IS 'bcrypt 密码哈希（不存明文，cost=12）';
COMMENT ON COLUMN users.role            IS '角色：owner 租户所有者 / admin 管理员 / member 普通成员，决定 RBAC 权限';
COMMENT ON COLUMN users.is_active       IS '是否启用：false 后 JWT 续期失败，无法登录';
COMMENT ON COLUMN users.created_at      IS '创建时间（UTC）';
COMMENT ON COLUMN users.updated_at      IS '最后更新时间（UTC）';


-- ---------------------------------------------------------------------------
-- 3) sessions 会话元数据表（方案 A：正文在 session_entries）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    session_id    VARCHAR(64)  NOT NULL,
    tenant_id     VARCHAR(36)  NOT NULL,
    user_id       VARCHAR(36)  NOT NULL,
    title         VARCHAR(256) NOT NULL DEFAULT '',
    status        VARCHAR(16)  NOT NULL DEFAULT 'active',
    message_count INTEGER      NOT NULL DEFAULT 0,
    metadata      TEXT         NOT NULL DEFAULT '{}',
    created_at    TIMESTAMP    NOT NULL,
    updated_at    TIMESTAMP    NOT NULL,
    CONSTRAINT pk_sessions PRIMARY KEY (session_id)
);
CREATE INDEX IF NOT EXISTS ix_sessions_tenant_id   ON sessions (tenant_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id     ON sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_tenant_user ON sessions (tenant_id, user_id);
COMMENT ON TABLE  sessions              IS '会话元数据表：只存会话概要信息，消息正文存放在 session_entries（方案 A append-only）';
COMMENT ON COLUMN sessions.session_id    IS '会话ID（主键，字符串，API 路径参数使用）';
COMMENT ON COLUMN sessions.tenant_id     IS '所属租户ID，跨租户查询一律返回 404';
COMMENT ON COLUMN sessions.user_id       IS '所属用户ID，列表接口只返回当前用户自己的会话';
COMMENT ON COLUMN sessions.title         IS '会话标题（用户可见名称）';
COMMENT ON COLUMN sessions.status        IS '会话状态：active 进行中 / archived 已归档';
COMMENT ON COLUMN sessions.message_count IS '消息条数缓存值，避免列表页多次 count 查询';
COMMENT ON COLUMN sessions.metadata      IS '扩展元信息（JSON 字符串），如来源渠道、模型名、标签';
COMMENT ON COLUMN sessions.created_at    IS '创建时间（UTC）';
COMMENT ON COLUMN sessions.updated_at    IS '最后更新时间（UTC）';


-- ---------------------------------------------------------------------------
-- 4) audit_logs 审计日志表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id         SERIAL      NOT NULL,
    tenant_id  VARCHAR(36)  NOT NULL,
    user_id    VARCHAR(36)  NOT NULL,
    session_id VARCHAR(64),
    action     VARCHAR(64)  NOT NULL,
    target     VARCHAR(256) NOT NULL DEFAULT '',
    result     VARCHAR(16)  NOT NULL DEFAULT 'success',
    detail     TEXT         NOT NULL DEFAULT '{}',
    created_at TIMESTAMP    NOT NULL,
    CONSTRAINT pk_audit_logs PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_id           ON audit_logs (tenant_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id             ON audit_logs (user_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_session_id          ON audit_logs (session_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action              ON audit_logs (action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at          ON audit_logs (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_action_time  ON audit_logs (tenant_id, action, created_at);
COMMENT ON TABLE  audit_logs            IS '审计日志表：登录、工具调用、计划执行、API Key 调用等操作的合规留痕';
COMMENT ON COLUMN audit_logs.id         IS '自增主键（SERIAL，仅日志表使用）';
COMMENT ON COLUMN audit_logs.tenant_id  IS '操作所属租户ID';
COMMENT ON COLUMN audit_logs.user_id    IS '操作人用户ID';
COMMENT ON COLUMN audit_logs.session_id IS '关联会话ID（可空，非会话类操作如登录为空）';
COMMENT ON COLUMN audit_logs.action     IS '操作类型：auth.login / auth.logout / agent.run / plan.create / plan.execute / api_key.call 等';
COMMENT ON COLUMN audit_logs.target     IS '操作对象：工具名 / plan_id / agent_id / 渠道名';
COMMENT ON COLUMN audit_logs.result     IS '执行结果：success 成功 / error 失败 / denied 被权限拒绝';
COMMENT ON COLUMN audit_logs.detail     IS '操作详情（JSON 字符串）：入参摘要、异常信息、耗时等';
COMMENT ON COLUMN audit_logs.created_at IS '发生时间（UTC）';


-- ---------------------------------------------------------------------------
-- 5) memories 长期记忆表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memories (
    id         VARCHAR(36) NOT NULL,
    tenant_id  VARCHAR(36) NOT NULL,
    user_id    VARCHAR(36) NOT NULL,
    session_id VARCHAR(64),
    content    TEXT        NOT NULL DEFAULT '',
    metadata   TEXT        NOT NULL DEFAULT '{}',
    created_at TIMESTAMP   NOT NULL,
    CONSTRAINT pk_memories PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_memories_tenant_id  ON memories (tenant_id);
CREATE INDEX IF NOT EXISTS ix_memories_user_id    ON memories (user_id);
CREATE INDEX IF NOT EXISTS ix_memories_session_id ON memories (session_id);
COMMENT ON TABLE  memories            IS '长期记忆表：Agent 跨会话沉淀的事实记忆，metadata 存 JSON 扩展信息';
COMMENT ON COLUMN memories.id         IS '记忆ID（主键，字符串UUID）';
COMMENT ON COLUMN memories.tenant_id  IS '所属租户ID，检索时强制隔离';
COMMENT ON COLUMN memories.user_id    IS '所属用户ID，支持按用户维度召回';
COMMENT ON COLUMN memories.session_id IS '来源会话ID（可空，跨会话沉淀的记忆为空）';
COMMENT ON COLUMN memories.content    IS '记忆正文（自然语言事实片段）';
COMMENT ON COLUMN memories.metadata   IS '扩展元信息（JSON 字符串），含向量 _embedding、tags、来源等';
COMMENT ON COLUMN memories.created_at IS '创建时间（UTC）';


-- ---------------------------------------------------------------------------
-- 6) plans 计划表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plans (
    plan_id    VARCHAR(64) NOT NULL,
    tenant_id  VARCHAR(36) NOT NULL,
    user_id    VARCHAR(36) NOT NULL,
    goal       TEXT        NOT NULL DEFAULT '',
    steps      TEXT        NOT NULL DEFAULT '[]',
    plan_text  TEXT        NOT NULL DEFAULT '',
    plan_hash  VARCHAR(80) NOT NULL DEFAULT '',
    approved   BOOLEAN     NOT NULL DEFAULT FALSE,
    status     VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP   NOT NULL,
    updated_at TIMESTAMP   NOT NULL,
    CONSTRAINT pk_plans PRIMARY KEY (plan_id)
);
CREATE INDEX IF NOT EXISTS ix_plans_tenant_id      ON plans (tenant_id);
CREATE INDEX IF NOT EXISTS ix_plans_user_id        ON plans (user_id);
CREATE INDEX IF NOT EXISTS ix_plans_tenant_created ON plans (tenant_id, created_at);
COMMENT ON TABLE  plans            IS '计划表：Agent 产出的多步执行计划，记录审批状态与执行状态';
COMMENT ON COLUMN plans.plan_id    IS '计划ID（主键，字符串，API 路径参数使用）';
COMMENT ON COLUMN plans.tenant_id  IS '所属租户ID';
COMMENT ON COLUMN plans.user_id    IS '创建人用户ID';
COMMENT ON COLUMN plans.goal       IS '计划目标：用户输入的自然语言任务描述';
COMMENT ON COLUMN plans.steps      IS '步骤列表（JSON 字符串），每个元素为 TaskSpec：task_id/goal/worker/depends_on 等';
COMMENT ON COLUMN plans.plan_text  IS '计划的可读文本形式（下发给前端展示或写入审计）';
COMMENT ON COLUMN plans.plan_hash  IS '计划内容哈希（SHA256 前缀），用于审批幂等与变更检测';
COMMENT ON COLUMN plans.approved   IS '是否已审批：false 待审批（HITL）/ true 已放行执行';
COMMENT ON COLUMN plans.status     IS '执行状态：pending 待执行 / running 执行中 / done 完成 / failed 失败 / cancelled 已取消';
COMMENT ON COLUMN plans.created_at IS '创建时间（UTC）';
COMMENT ON COLUMN plans.updated_at IS '最后更新时间（UTC）';


-- ---------------------------------------------------------------------------
-- 7) session_entries 会话事件流水表（append-only）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS session_entries (
    entry_id   VARCHAR(64) NOT NULL,
    seq        BIGINT      NOT NULL,
    kind       VARCHAR(32) NOT NULL,
    content    TEXT        NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_session_entries PRIMARY KEY (entry_id)
);
CREATE INDEX IF NOT EXISTS ix_session_entries_seq  ON session_entries (seq);
CREATE INDEX IF NOT EXISTS ix_session_entries_kind ON session_entries (kind);
COMMENT ON TABLE  session_entries            IS '会话事件流水表：append-only 追加写，按 seq 递增保存每条消息/事件，不覆盖历史';
COMMENT ON COLUMN session_entries.entry_id   IS '事件ID（主键，字符串，幂等写入键：ON CONFLICT 时不重复插入）';
COMMENT ON COLUMN session_entries.seq        IS '会话内自增序号，同一 session 内严格递增，用于按序回放消息';
COMMENT ON COLUMN session_entries.kind       IS '事件类型：message 消息 / tool_call 工具调用 / tool_result 工具结果 / event 系统事件';
COMMENT ON COLUMN session_entries.content    IS '事件内容（JSON 字符串，canonical 序列化后的消息体）';
COMMENT ON COLUMN session_entries.created_at IS '创建时间（Unix 时间戳，float，秒级精度）';


-- ---------------------------------------------------------------------------
-- 核对：执行后应为 表=7、表注释=7
-- ---------------------------------------------------------------------------
SELECT COUNT(*) AS table_count
FROM information_schema.tables
WHERE table_schema = 'public';

SELECT COUNT(*) AS commented_tables
FROM pg_description d
JOIN pg_class c ON c.oid = d.objoid
WHERE d.objsubid = 0
  AND c.relnamespace = 'public'::regnamespace;


-- ============================================================================
-- 回退（仅需彻底清空本库时手动取消注释执行；会丢失全部数据）
-- ============================================================================
-- DROP TABLE IF EXISTS session_entries CASCADE;
-- DROP TABLE IF EXISTS plans CASCADE;
-- DROP TABLE IF EXISTS memories CASCADE;
-- DROP TABLE IF EXISTS audit_logs CASCADE;
-- DROP TABLE IF EXISTS sessions CASCADE;
-- DROP TABLE IF EXISTS users CASCADE;
-- DROP TABLE IF EXISTS tenants CASCADE;


-- ---------------------------------------------------------------------------
-- 执行记录
-- 时间：2026-11-25
-- 环境：Docker harness-pg（postgres:16，localhost:5433/harness）
-- 命令：psql -f V20261125_platform_schema_init.sql（PG）
--       SQLite 由应用启动时 SQLModel.metadata.create_all 建表
-- 结果：成功。PG 7 表 / 63 条表字段注释全部写入；SQLite 7 表建齐（无注释）
-- 核对：PG 表注释=7、字段注释=56；两库表数=7
-- 种子：PG / SQLite 各写入 dev-tenant + admin(owner) + demo(member)
-- ---------------------------------------------------------------------------
