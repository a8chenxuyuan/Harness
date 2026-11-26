-- ============================================================================
-- 启动恢复状态语义（W3-KERN-01，2026-11-26）
--
-- 背景：进程重启后内存态运行全部丢失，数据库可能残留中间态：
--         agent_runs.status      = running
--         session_messages.status = streaming
--         plans.status            = running
--       服务启动时（init_db 之后）统一收敛为终态：
--         running   → interrupted
--         streaming → failed
--
-- 变更：不改表结构（VARCHAR(16) 已容纳 interrupted），仅覆盖状态列注释。
--
-- 幂等：COMMENT 覆盖写；恢复逻辑本身只命中中间态，可重复执行。
--
-- 适用：PostgreSQL（SQLite 开发库无列注释，由应用层恢复逻辑处理）。
-- ============================================================================

COMMENT ON COLUMN agent_runs.status IS
    '状态：queued / running / paused / succeeded / failed / cancelled / interrupted（服务重启遗留 running 自动收敛）';

COMMENT ON COLUMN session_messages.status IS
    '消息状态：streaming 生成中 / completed 完成 / failed 失败 / cancelled 用户取消（重启遗留 streaming 收敛为 failed）';

COMMENT ON COLUMN plans.status IS
    '计划状态：pending / approved / running / done / failed / cancelled / interrupted（重启遗留 running 自动收敛）';


-- ---------------------------------------------------------------------------
-- 核对：三张表的状态注释
-- ---------------------------------------------------------------------------
SELECT c.relname AS table_name, col_description(c.oid, a.attnum) AS status_comment
FROM pg_class c
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'status'
WHERE c.relname IN ('agent_runs', 'session_messages', 'plans')
ORDER BY c.relname;


-- ============================================================================
-- 回退（仅恢复注释，不影响数据）
-- ============================================================================
-- COMMENT ON COLUMN agent_runs.status IS
--     '状态：queued / running / paused / succeeded / failed / cancelled / interrupted';
-- COMMENT ON COLUMN session_messages.status IS
--     '消息状态：streaming 生成中 / completed 完成 / failed 失败 / cancelled 用户取消';
-- COMMENT ON COLUMN plans.status IS
--     '计划状态：pending / approved / running / done / failed / cancelled';


-- ---------------------------------------------------------------------------
-- 执行记录
-- 时间：2026-11-26
-- 环境：Docker harness-pg（postgres:16，localhost:5433/harness）
-- 结果：待执行（本地 SQLite 无列注释，应用层恢复已生效）。
-- ---------------------------------------------------------------------------
