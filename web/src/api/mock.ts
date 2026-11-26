/** 前端 mock 数据（会话 / 运行）：VITE_USE_MOCK=true 时接口走这里。 */
import type {
  LoginData,
  RunData,
  SessionDetail,
  SessionListData,
  SessionSummary,
  StreamCancelData,
  UserInfo,
} from "./types";

const TITLES = [
  "排查订单超时",
  "周报数据汇总",
  "飞书渠道接入排查",
  "沙箱路径越权测试",
  "工具调用耗时分析",
  "多租户隔离验证",
  "计划重规划演练",
  "审计日志回溯",
];

/** 固定 23 条会话，保证演示数据稳定（消息 mock 复用同一列表）。 */
export const allSessions: SessionDetail[] = Array.from({ length: 23 }, (_, index) => {
  const title = `${TITLES[index % TITLES.length]}${index >= TITLES.length ? ` #${index + 1}` : ""}`;
  const archived = index % 7 === 5;
  return {
    session_id: `s-${(index + 1).toString(16).padStart(4, "0")}c4`,
    title,
    status: archived ? "archived" : "active",
    message_count: (index * 3) % 14,
    updated_at: relativeTime(index),
    created_at: "2026-11-24 09:00:00",
    tenant_id: "dev-tenant",
  };
});

/** 把序号转成"x 分钟前"这种可读时间。 */
function relativeTime(index: number): string {
  if (index === 0) return "2 分钟前";
  if (index === 1) return "18 分钟前";
  if (index < 6) return `${index * 27} 分钟前`;
  if (index < 12) return `${index - 5} 小时前`;
  return `${index - 11} 天前`;
}

/** 统一延迟返回，模拟网络耗时。 */
export function delay<T>(value: T, ms = 260): Promise<T> {
  return new Promise((resolve) => window.setTimeout(() => resolve(value), ms));
}

export async function mockLogin(username: string, password: string): Promise<LoginData> {
  if (!username || !password) {
    throw new Error("用户名和密码不能为空");
  }
  return delay({
    access_token: "mock-access-token",
    refresh_token: "mock-refresh-token",
    token_type: "bearer",
    expires_in: 900,
  }, 420);
}

export async function mockMe(): Promise<UserInfo> {
  return delay({ user_id: "dev-user", tenant_id: "dev-tenant", role: "owner" }, 120);
}

export async function mockListSessions(
  page: number,
  size: number,
  status?: string,
): Promise<SessionListData> {
  const scoped =
    !status || status === "all"
      ? allSessions
      : allSessions.filter((item) => item.status === status);
  const start = (page - 1) * size;
  const items: SessionSummary[] = scoped
    .slice(start, start + size)
    .map(({ created_at, tenant_id, ...rest }) => {
      void created_at;
      void tenant_id;
      return rest;
    });
  return delay({ items, total: scoped.length, page, size });
}

export async function mockGetSession(sessionId: string): Promise<SessionDetail> {
  const found = allSessions.find((item) => item.session_id === sessionId);
  if (!found) throw new Error("会话不存在");
  return delay(found, 200);
}

/** 归档 / 恢复会话（只改状态）。 */
export async function mockArchiveSession(
  sessionId: string,
  archived: boolean,
): Promise<SessionDetail> {
  const found = allSessions.find((item) => item.session_id === sessionId);
  if (!found) throw new Error("会话不存在");
  found.status = archived ? "archived" : "active";
  found.updated_at = "刚刚";
  return delay(found, 150);
}

interface RunState {
  startedAt: number;
  cancelled: boolean;
}

const runs = new Map<string, RunState>();
let runSeq = 0;

/** 启动一次 mock 运行，4 秒后自动完成。 */
export async function mockStartRun(goal: string): Promise<RunData> {
  if (!goal.trim()) throw new Error("目标不能为空");
  const runId = `run-${(++runSeq).toString(16).padStart(4, "0")}`;
  runs.set(runId, { startedAt: Date.now(), cancelled: false });
  return delay({ run_id: runId, status: "running", output: null }, 380);
}

/** 按已过时间推算运行状态。 */
export async function mockRunStatus(runId: string): Promise<RunData> {
  const state = runs.get(runId);
  if (!state) throw new Error("运行不存在");
  const elapsed = Date.now() - state.startedAt;
  if (state.cancelled) {
    return delay({ run_id: runId, status: "cancelled", output: null, error: "人工取消" }, 80);
  }
  if (elapsed < 4000) {
    return delay({ run_id: runId, status: "running", output: null }, 80);
  }
  return delay({
    run_id: runId,
    status: "completed",
    output: "上周订单超时集中在 21:00-23:00，主要来自小程序渠道。\n建议：1) 该时段扩容；2) 增加超时重试；3) 对小程序下单链路单独埋点。",
    metrics: { tokens: 3842, tool_calls: 4, elapsed_ms: 4000 },
  }, 80);
}

export async function mockCancelRun(runId: string): Promise<RunData> {
  const state = runs.get(runId);
  if (state) state.cancelled = true;
  return delay({ run_id: runId, status: "cancelled", output: null }, 90);
}

/** 标记 mock 流式运行为已取消。 */
export async function mockCancelStreamRun(runId: string): Promise<StreamCancelData> {
  const state = runs.get(runId);
  if (state) state.cancelled = true;
  return delay({ run_id: runId, status: "cancelled" }, 80);
}
