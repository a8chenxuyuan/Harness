/** 前端 mock 数据（会话消息）：列表 / 发送 / 重试 / 分支。 */
import { allSessions, delay } from "./mock";
import type {
  ChatMessage,
  ChatMessageListData,
  MessageBranchData,
  MessageRetryData,
  RunData,
  SessionDetail,
} from "./types";

const messages = new Map<string, ChatMessage[]>();
let msgSeq = 0;

/** 新建会话（插入列表头部，并初始化消息列表）。 */
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
    run_id: `run-${Date.now().toString(16)}`,
    status: "completed",
    output: `（mock）收到：${text}`,
  }, 600);
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
