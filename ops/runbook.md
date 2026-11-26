# Harness 运维 Runbook（W3-OBS-02）

适用版本：`feat/w3-reliability` 及之后。
配套告警：`ops/prometheus/alerts.yml`。

## 快速入口

| 能力 | 入口 |
| --- | --- |
| Prometheus 抓取 | `GET /metrics`（内网采集，不鉴权） |
| HTTP 指标摘要 | `GET /api/v1/observability/metrics`（owner/admin） |
| 就绪探针 | `GET /api/v1/ready` |
| 审计日志 | `GET /api/v1/audit-logs` / `GET /api/v1/audit-logs/export` |
| 运行记录 | `GET /api/v1/runs` / `GET /api/v1/runs/{run_id}` |
| 租户配额 | `GET/PUT /api/v1/tenant/quotas`（owner/admin） |

排障时先用响应头 `X-Request-ID` 串日志；`agent.run` / `model.stream` /
`tool.execute` span 会自动带上 `request_id`、`tenant_id`、`session_id`、`run_id`。

---

## HarnessHighErrorRate

**现象**：5xx 占比超过 5% 持续 5 分钟。

1. 看 `/api/v1/observability/metrics` 的 `recent_errors`，按 `path` 归因。
2. 用 `X-Request-ID` 在日志中检索完整栈。
3. 常见原因：
   - 数据库不可用 → 查 `/api/v1/ready` 与引擎日志；
   - 模型配置错误 → 查 `ModelConfigError`；
   - 未捕获异常 → 查 `unexpected error` 日志。
4. 若是新版本引入，回滚到上一个 tag；否则按具体异常修复。

## HarnessHighLatencyP95

**现象**：HTTP P95 超过 10 秒持续 10 分钟。

1. 区分接口：`/agents/run`（同步）天然慢，优先看 `/sessions`、`/runs` 等管理接口。
2. 查模型指标：`harness_ttft_seconds`、`harness_model_retry_total`。
3. 查数据库：SQLite 仅开发用；生产 PG 检查慢查询与连接池。
4. 临时缓解：调大 `HARNESS_MODEL__TIMEOUT` 之前先确认上游是否故障；
   必要时通过配额接口降低单租户并发。

## HarnessRateLimitBurst

**现象**：`harness_rate_limited_total` 持续增长。

1. 按 `scope` 看是登录、run、消息还是审计导出。
2. 登录限流突增 → 可能是撞库，检查来源 IP（`X-Forwarded-For`）。
3. run/stream 突增 → 检查是否有客户端无限重试；提醒使用 `Idempotency-Key`。
4. 确认是业务增长而非攻击后，再调整 `rate_limit.py` 中的阈值。

## HarnessModelRetryStorm

**现象**：模型重试速率异常。

1. 看 `harness_model_retry_total{reason=...}`：`timeout` 还是 `error`。
2. 查供应商状态页与网络连通性。
3. 若为超时：确认 `HARNESS_MODEL__TIMEOUT` 是否过小。
4. 重试只发生在首 token 之前；若大量重试，通常上游已不可用。

## HarnessModelCircuitOpen

**现象**：模型熔断被打开。

1. 看 `harness_model_circuit_open_total{model=...}` 定位模型。
2. 熔断冷却期内请求会快速失败（`ModelUnavailableError`）。
3. 上游恢复后等待 `HARNESS_MODEL__CIRCUIT_COOLDOWN` 自动半开；
   紧急情况下重启进程可清空进程内熔断状态。
4. 复盘连续失败原因，避免单纯调大阈值掩盖问题。

## HarnessTTFTSlow

**现象**：首 token P95 超过 15 秒。

1. 确认是否特定模型 / 特定租户；span `model.stream` 可看单次耗时。
2. 检查提示词是否过长、是否触发大量工具调用。
3. 结合 `harness_cache_hit_ratio` 判断缓存是否失效。

## HarnessSandboxViolation

**现象**：出现沙箱越界拦截（正常恒为 0）。

1. 该指标为安全红线，立即按 `reason` 检索日志。
2. 定位 `tenant_id` / `user_id` / `session_id`，必要时冻结账号。
3. 检查工具入参与工作目录配置，确认是否存在逃逸尝试。
4. 保留审计日志与 span，事后补充规则。

## HarnessServiceDown

**现象**：Prometheus 抓取失败 2 分钟。

1. 检查进程：`uvicorn harness.app:create_app --factory` 是否存活。
2. 检查 `/metrics` 端口与防火墙。
3. 检查启动日志：`db.engine: 初始化失败`、`recovery: 启动恢复失败`。
4. 重启后确认启动恢复已收敛遗留中间态（日志 `recovery: 收敛重启遗留中间态`）。
