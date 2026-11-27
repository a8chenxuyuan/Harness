/** 与后端 DTO 对齐的前端类型定义（字段名与 /api/v1 保持一致）。 */

/** 后端统一响应包：code=0 表示成功。 */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

/** 登录返回。 */
export interface LoginData {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** 当前用户。 */
export interface UserInfo {
  user_id: string;
  tenant_id: string;
  role: string;
  /** 可见页面 key 列表（多角色并集，/auth/me 返回）。 */
  allowed_pages?: string[];
}

/** 权限管理页的用户行（/permissions/users）。 */
export interface PermissionUser {
  user_id: string;
  username: string;
  email: string;
  primary_role: string;
  roles: string[];
  is_active: boolean;
}

/** 会话摘要（列表行）。 */
export interface SessionSummary {
  session_id: string;
  title: string;
  status: string;
  message_count: number;
  updated_at?: string;
}

/** 会话详情。 */
export interface SessionDetail extends SessionSummary {
  tenant_id?: string;
  created_at?: string;
}

/** 消息内容块（text / tool_call / tool_result / thinking）。 */
export interface MessagePart {
  type: string;
  text?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  content?: string;
  /** tool_call 块：执行成功与否（undefined 表示仍在执行）。 */
  ok?: boolean;
  execution_time_ms?: number;
}

/** 单条会话消息。 */
export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | "tool" | string;
  parts: MessagePart[];
  text: string;
  seq: number;
  parent_id: string | null;
  status: string;
  created_at: string | null;
}

/** 消息列表（seq 游标分页）。 */
export interface ChatMessageListData {
  items: ChatMessage[];
  next_cursor: number;
  has_more: boolean;
}

/** 会话列表分页数据。 */
export interface SessionListData {
  items: SessionSummary[];
  total: number;
  page: number;
  size: number;
}

/** Agent 运行状态。 */
export interface RunData {
  run_id: string;
  status: "running" | "completed" | "failed" | "cancelled" | string;
  output: string | null;
  error?: string | null;
  metrics?: Record<string, number | string>;
}

/** SSE message_start 事件。 */
export interface StreamStartData {
  run_id: string;
  message_id: string;
  session_id: string;
  seq: number;
}

/** SSE tool_call 事件中的单条工具调用。 */
export interface StreamToolCall {
  id?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  ok?: boolean;
  output?: string | null;
  error?: string | null;
  execution_time_ms?: number;
}

/** SSE tool_call 事件：start=开始执行，end=执行完成。 */
export interface StreamToolData {
  status: "start" | "end";
  calls?: StreamToolCall[];
  results?: StreamToolCall[];
}

/** SSE message_end 事件。 */
export interface StreamEndData {
  status: "completed" | "cancelled" | "failed";
  message: ChatMessage;
  metrics?: Record<string, number>;
  error?: string | null;
}

/** POST /agents/runs/{run_id}/cancel 响应。 */
export interface StreamCancelData {
  run_id: string;
  status: string;
}

/** POST /sessions/{sid}/messages/{mid}/retry 响应。 */
export interface MessageRetryData {
  session_id: string;
  message_id: string;
  text: string;
  removed_message_ids: string[];
}

/** POST /sessions/{sid}/messages/{mid}/branch 响应。 */
export interface MessageBranchData {
  session_id: string;
  source_session_id: string;
  source_message_id: string;
  title: string;
  message_count: number;
}

/** 审计日志筛选参数。 */
export interface AuditQuery {
  page?: number;
  size?: number;
  action?: string;
  user_id?: string;
  session_id?: string;
  result?: string;
  since?: string;
  until?: string;
}

/** 单条审计日志（detail 为对象，created_at 为 ISO UTC）。 */
export interface AuditLogItem {
  id: number;
  user_id: string;
  session_id: string | null;
  action: string;
  target: string;
  result: string;
  detail: Record<string, unknown>;
  created_at: string;
}

/** GET /api/v1/audit-logs 响应。 */
export interface AuditLogListData {
  items: AuditLogItem[];
  total: number;
  page: number;
  size: number;
}

/** 按状态类分组的请求数。 */
export interface HttpStatusCounts {
  ok: number;
  redirect: number;
  client_error: number;
  server_error: number;
}

/** 最近一条失败请求。 */
export interface RecentHttpError {
  time: string;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  request_id: string;
}

/** GET /api/v1/observability/metrics 响应。 */
export interface MetricsSummary {
  total_requests: number;
  error_requests: number;
  error_rate: number;
  avg_ms: number;
  p95_ms: number;
  status_counts: HttpStatusCounts;
  recent_errors: RecentHttpError[];
  uptime_seconds: number;
  prometheus_available: boolean;
}

// ---------------------------------------------------------------------------
// Skill 管理（W4-01）
// ---------------------------------------------------------------------------

/** 单个 Skill 的展示项。 */
export interface SkillItem {
  name: string;
  description: string;
  version: string;
  triggers: string[];
  tools: string[];
  custom_message: string;
  /** 是否启用；禁用后 SkillTrigger 不再命中 */
  enabled: boolean;
  /** 来源层：runtime / user / project / bundled */
  source: string;
  metadata: Record<string, unknown>;
}

/** GET /api/v1/skills 响应。 */
export interface SkillListData {
  items: SkillItem[];
  total: number;
}

/** POST /api/v1/skills 请求体。 */
export interface SkillRegisterBody {
  name: string;
  description?: string;
  version?: string;
  triggers?: string[];
  tools?: string[];
  custom_message?: string;
  metadata?: Record<string, unknown>;
}

/** POST /api/v1/skills/trigger-test 请求体。 */
export interface SkillTriggerTestBody {
  text: string;
}

/** POST /api/v1/skills/trigger-test 响应中单个命中项。 */
export interface SkillTriggerMatch {
  name: string;
  matched_trigger: string;
}

/** POST /api/v1/skills/trigger-test 响应。 */
export interface SkillTriggerTestData {
  matched: SkillTriggerMatch[];
  total_matches: number;
}

/** PATCH /api/v1/skills/{name} 请求体。 */
export interface SkillPatchBody {
  enabled: boolean;
}

/** GET /api/v1/skills/{name}/versions 响应中的单个历史版本。 */
export interface SkillVersionItem {
  version: string;
  description: string;
  source: string;
  replaced_at: string;
}

/** GET /api/v1/skills/{name}/versions 响应。 */
export interface SkillVersionsData {
  items: SkillVersionItem[];
  total: number;
}

// ---------------------------------------------------------------------------
// 工具市场 / MCP 注册（W4-EXT-02）
// ---------------------------------------------------------------------------

/** 工具市场中单个工具的展示项。 */
export interface ToolMarketItem {
  name: string;
  description: string;
  /** false=写类工具，调试面板拒绝执行 */
  readonly: boolean;
  parameters: Record<string, unknown>;
  /** builtin（内置）/ mcp（外部 MCP server） */
  source: string;
  server: string | null;
}

/** GET /api/v1/tools/market 响应。 */
export interface ToolMarketData {
  items: ToolMarketItem[];
  total: number;
}

/** POST /api/v1/tools/{name}/debug 响应。 */
export interface ToolDebugData {
  ok: boolean;
  output: string;
  error: string | null;
  execution_time_ms: number;
}

/** 已注册 MCP server 的展示项。 */
export interface McpServerItem {
  name: string;
  command: string;
  args: string[];
  /** 环境变量键名列表（值不回传） */
  env_keys: string[];
  registered_at: string;
  tools: string[];
  tool_count: number;
}

/** GET /api/v1/mcp/servers 响应。 */
export interface McpServerListData {
  items: McpServerItem[];
  total: number;
}

/** POST /api/v1/mcp/servers 请求体。 */
export interface McpServerRegisterBody {
  name: string;
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

// ---------------------------------------------------------------------------
// API Key 机器调用（W4-API-01）
// ---------------------------------------------------------------------------

/** 单个 API Key 的脱敏展示项。 */
export interface ApiKeyItem {
  id: string;
  name: string;
  /** key 前缀（hk_ + 8 位，供人工辨认） */
  key_prefix: string;
  tenant_id: string;
  created_by: string;
  scopes: string;
  is_active: boolean;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string | null;
}

/** GET /api/v1/api-keys 响应。 */
export interface ApiKeyListData {
  items: ApiKeyItem[];
  total: number;
}

/** POST /api/v1/api-keys 请求体。 */
export interface ApiKeyCreateBody {
  name: string;
  expires_in_days?: number | null;
}

/** POST /api/v1/api-keys 响应（明文仅此一次）。 */
export interface ApiKeyCreateData {
  key: ApiKeyItem;
  plaintext: string;
}

// ---------------------------------------------------------------------------
// Memory 管理（W4-02）
// ---------------------------------------------------------------------------

/** 单条长期记忆。 */
export interface MemoryItem {
  item_id: string;
  content: string;
  session_id: string;
  tags: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

/** GET /api/v1/memories 响应。 */
export interface MemoryListData {
  items: MemoryItem[];
  total: number;
  limit: number;
  offset: number;
}

/** POST /api/v1/memories 请求体。 */
export interface MemorySaveBody {
  content: string;
  session_id?: string | null;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

/** POST /api/v1/memories 响应。 */
export interface MemorySaveData {
  item_id: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Webhook 事件推送（W4-CHAN-03）
// ---------------------------------------------------------------------------

/** 单个 Webhook 订阅的脱敏展示项。 */
export interface WebhookItem {
  id: string;
  name: string;
  url: string;
  /** 签名密钥前 8 位（供人工辨认） */
  secret_prefix: string;
  /** 关心的事件类型；空数组 = 全部事件 */
  event_types: string[];
  is_active: boolean;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
}

/** GET /api/v1/webhooks 响应。 */
export interface WebhookListData {
  items: WebhookItem[];
  total: number;
}

/** POST /api/v1/webhooks 请求体。 */
export interface WebhookCreateBody {
  name: string;
  url: string;
  /** 不传或空 = 订阅全部事件 */
  event_types?: string[] | null;
}

/** POST /api/v1/webhooks 响应（密钥明文仅此一次）。 */
export interface WebhookCreateData {
  webhook: WebhookItem;
  secret: string;
}

/** 单条投递记录。 */
export interface WebhookDeliveryItem {
  id: string;
  subscription_id: string;
  event_type: string;
  /** success | failed */
  status: string;
  status_code: number | null;
  attempts: number;
  duration_ms: number | null;
  response_body: string;
  created_at: string | null;
}

/** GET /api/v1/webhooks/{id}/deliveries 响应。 */
export interface WebhookDeliveryListData {
  items: WebhookDeliveryItem[];
  total: number;
}

/** POST /api/v1/webhooks/{id}/test 响应。 */
export interface WebhookTestData {
  delivery: WebhookDeliveryItem;
}
