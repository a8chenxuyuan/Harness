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
}

/** 会话摘要（列表行）。 */
export interface SessionSummary {
  session_id: string;
  title: string;
  status: string;
  message_count: number;
  updated_at: string;
}

/** 会话详情。 */
export interface SessionDetail extends SessionSummary {
  tenant_id?: string;
  created_at?: string;
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
  metrics?: Record<string, number>;
}
