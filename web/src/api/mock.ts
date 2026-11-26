/** 前端 mock 数据：VITE_USE_MOCK=true 时全部接口走这里，不依赖后端。 */
import type {
  ChatMessage,
  ChatMessageListData,
  LoginData,
  MessageBranchData,
  MessageRetryData,
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

/** 固定 23 条会话，保证演示数据稳定。 */
const allSessions: SessionDetail[] = Array.from({ length: 23 }, (_, index) => {
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

function delay<T>(value: T, ms = 260): Promise<T> {
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

export async function mockListSessions(page: number, size: number): Promise<SessionListData> {
  const start = (page - 1) * size;
  const items: SessionSummary[] = allSessions.slice(start, start + size).map(({ created_at, tenant_id, ...rest }) => {
    void created_at;
    void tenant_id;
    return rest;
  });
  return delay({ items, total: allSessions.length, page, size });
}

export async function mockGetSession(sessionId: string): Promise<SessionDetail> {
  const found = allSessions.find((item) => item.session_id === sessionId);
  if (!found) throw new Error("会话不存在");
  return delay(found, 200);
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

// ---------------------------------------------------------------------------
// 会话与消息
// ---------------------------------------------------------------------------

const messages = new Map<string, ChatMessage[]>();
let msgSeq = 0;

/** 新建会话（插入列表头部）。 */
export async function mockCreateSession(title: string): Promise<SessionDetail> {
  const session: SessionDetail = {
    session_id: `s-${Date.now().toString(16)}`,
    title: title || "未命名会话",
    status: "active",
    message_count: 0,
    updated_at: "刚刚",
    created_at: new Date().toISOString(),
    tenant_id: "dev-tenant",
  };
  allSessions.unshift(session);
  messages.set(session.session_id, []);
  return delay(session, 200);
}

/** 读取会话消息（seq 游标）。 */
export async function mockListMessages(
  sessionId: string,
  afterSeq = 0,
  limit = 50,
): Promise<ChatMessageListData> {
  const list = (messages.get(sessionId) ?? []).filter((item) => item.seq > afterSeq);
  const page = list.slice(0, limit);
  return delay({
    items: page,
    next_cursor: page.length ? page[page.length - 1].seq : afterSeq,
    has_more: list.length > limit,
  }, 150);
}

/** 发送一条用户消息，并在 600ms 后追加一条模拟助手回复。 */
export async function mockSendMessage(sessionId: string, text: string): Promise<RunData> {
  const list = messages.get(sessionId) ?? [];
  const now = new Date().toISOString();
  list.push({
    id: `m-${++msgSeq}`,
    session_id: sessionId,
    role: "user",
    parts: [{ type: "text", text }],
    text,
    seq: list.length + 1,
    parent_id: null,
    status: "completed",
    created_at: now,
  });
  list.push({
    id: `m-${++msgSeq}`,
    session_id: sessionId,
    role: "assistant",
    parts: [{ type: "text", text: `（mock）收到：${text}` }],
    text: `（mock）收到：${text}`,
    seq: list.length + 1,
    parent_id: null,
    status: "completed",
    created_at: now,
  });
  messages.set(sessionId, list);

  const found = allSessions.find((item) => item.session_id === sessionId);
  if (found) {
    found.message_count = list.length;
    found.updated_at = "刚刚";
  }
  return delay({
    run_id: `run-${(++runSeq).toString(16).padStart(4, "0")}`,
    status: "completed",
    output: `（mock）收到：${text}`,
  }, 600);
}

// ---------------------------------------------------------------------------
// 流式取消 / 重试 / 分支
// ---------------------------------------------------------------------------

/** 标记 mock 运行为已取消。 */
export async function mockCancelStreamRun(runId: string): Promise<StreamCancelData> {
  const state = runs.get(runId);
  if (state) state.cancelled = true;
  return delay({ run_id: runId, status: "cancelled" }, 80);
}

/** 软删失败消息与其上一条 user 消息，返回原文。 */
export async function mockRetryMessage(
  sessionId: string,
  messageId: string,
): Promise<MessageRetryData> {
  const list = messages.get(sessionId) ?? [];
  const index = list.findIndex((item) => item.id === messageId);
  if (index < 0) throw new Error("消息不存在");
  const target = list[index];
  if (target.role !== "assistant" || !["failed", "cancelled"].includes(target.status)) {
    throw new Error("只有失败或取消的助手消息可以重试");
  }
  if (index !== list.length - 1) throw new Error("只能重试最后一条消息");

  const source = index > 0 && list[index - 1].role === "user" ? list[index - 1] : null;
  const removed: string[] = [];
  const kept = list.filter((item) => {
    if (item === target || item === source) {
      removed.push(item.id);
      return false;
    }
    return true;
  });
  list.length = 0;
  list.push(...kept);

  const found = allSessions.find((item) => item.session_id === sessionId);
  if (found) found.message_count = list.length;
  return delay({
    session_id: sessionId,
    message_id: messageId,
    text: source?.text ?? "",
    removed_message_ids: removed,
  }, 140);
}

/** 以目标消息为分界复制到新会话。 */
export async function mockBranchMessage(
  sessionId: string,
  messageId: string,
): Promise<MessageBranchData> {
  const sourceSession = allSessions.find((item) => item.session_id === sessionId);
  if (!sourceSession) throw new Error("会话不存在");
  const list = messages.get(sessionId) ?? [];
  const index = list.findIndex((item) => item.id === messageId);
  if (index < 0) throw new Error("消息不存在");

  const newSessionId = `s-${Date.now().toString(16)}b`;
  const copied: ChatMessage[] = list.slice(0, index + 1).map((item, position) => ({
    ...item,
    id: `m-${++msgSeq}`,
    session_id: newSessionId,
    seq: position + 1,
    parent_id: item.id,
  }));
  const title = `${sourceSession.title || "会话"} · 分支`;
  allSessions.unshift({
    session_id: newSessionId,
    title,
    status: "active",
    message_count: copied.length,
    updated_at: "刚刚",
    created_at: new Date().toISOString(),
    tenant_id: "dev-tenant",
  });
  messages.set(newSessionId, copied);

  return delay({
    session_id: newSessionId,
    source_session_id: sessionId,
    source_message_id: messageId,
    title,
    message_count: copied.length,
  }, 160);
}
