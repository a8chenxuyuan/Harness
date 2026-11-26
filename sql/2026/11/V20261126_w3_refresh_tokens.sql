-- ============================================================================
-- refresh_tokens 刷新令牌轮换与吊销（W3-SEC-01，2026-11-26）
--
-- 背景：原 refresh 只是重新签发 JWT，服务端无状态：
--   - 旧 refresh token 在 7 天内始终可用，泄露后无法主动作废
--   - 无法识别 refresh token 重放
--
-- 方案：登录/注册时把 refresh token 的 jti 与 SHA-256 哈希落库；
--       刷新时校验并轮换（旧记录 revoked_at + replaced_by）；
--       旧 token 再次使用视为重放，吊销该用户全部 refresh token；
--       登出可携带 refresh token 主动吊销。
--
-- 注意：只存哈希，不存明文 token。
--
-- 幂等：CREATE TABLE / INDEX IF NOT EXISTS + COMMENT 覆盖写。
--
-- 适用：PostgreSQL。SQLite 开发库由 SQLModel.metadata.create_all 建表。
-- ============================================================================

CREATE TABLE IF NOT EXISTS refresh_tokens (
    jti         VARCHAR(64) NOT NULL,
    user_id     VARCHAR(36) NOT NULL,
    tenant_id   VARCHAR(36) NOT NULL,
    token_hash  VARCHAR(64) NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    replaced_by VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_refresh_tokens PRIMARY KEY (jti)
);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user
    ON refresh_tokens (user_id);

COMMENT ON TABLE  refresh_tokens             IS 'refresh token 记录：轮换、吊销与重放检测';
COMMENT ON COLUMN refresh_tokens.jti         IS 'JWT 的 jti（主键）';
COMMENT ON COLUMN refresh_tokens.user_id     IS '所属用户ID';
COMMENT ON COLUMN refresh_tokens.tenant_id   IS '所属租户ID';
COMMENT ON COLUMN refresh_tokens.token_hash  IS 'refresh token 的 SHA-256 哈希（不存明文）';
COMMENT ON COLUMN refresh_tokens.expires_at  IS '过期时间（UTC，与 JWT exp 一致）';
COMMENT ON COLUMN refresh_tokens.revoked_at  IS '吊销时间（UTC；为空表示有效）';
COMMENT ON COLUMN refresh_tokens.replaced_by IS '轮换后的新 jti（用于追踪链路）';
COMMENT ON COLUMN refresh_tokens.created_at  IS '签发时间（UTC）';


-- ---------------------------------------------------------------------------
-- 核对：表存在
-- ---------------------------------------------------------------------------
SELECT COUNT(*) AS table_exists
FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'refresh_tokens';


-- ============================================================================
-- 回退（会丢失吊销状态，回退后旧 refresh token 重新可用）
-- ============================================================================
-- DROP TABLE IF EXISTS refresh_tokens CASCADE;


-- ---------------------------------------------------------------------------
-- 执行记录
-- 时间：2026-11-26
-- 环境：Docker harness-pg（postgres:16，localhost:5433/harness）
-- 结果：待执行（本地 SQLite 由 create_all 建表）。
-- ---------------------------------------------------------------------------
