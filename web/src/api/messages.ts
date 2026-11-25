/** 会话消息接口：读取消息列表 / 发送消息（走 Agent 运行，落 user+assistant 消息）。 */
import { get, post } from "./http";
import { mockListMessages, mockSendMessage } from "./mock";
import type { ChatMessageListData, RunData } from "./types";

const useMock = import.meta.env.VITE_USE_MOCK !== "false";

/** GET /sessions/{id}/messages?after_seq=&limit= */
export async function listMessages(
  sessionId: string,
  afterSeq = 0,
  limit = 50,
): Promise<ChatMessageListData> {
  if (useMock) return mockListMessages(sessionId, afterSeq, limit);
  return get<ChatMessageListData>(`/sessions/${sessionId}/messages`, {
    after_seq: afterSeq,
    limit,
  });
}

/**
 * 发送消息：POST /agents/run（带 conversation_id）。
 *
 * 由后端 AgentService 统一落 user / assistant 两条消息，
 * 避免前端分别写消息与运行记录造成顺序不一致。
 */
export async function sendMessage(sessionId: string, text: string): Promise<RunData> {
  if (useMock) return mockSendMessage(sessionId, text);
  return post<RunData>("/agents/run", {
    goal: text,
    mode: "single",
    conversation_id: sessionId,
  });
}
