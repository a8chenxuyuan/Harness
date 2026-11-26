/** 会话消息接口：读取消息列表 / 发送消息（同步或 SSE 流式）。 */
import { ApiError, get, post, TOKEN_KEY } from "./http";
import { mockCancelStreamRun } from "./mock";
import {
  mockBranchMessage,
  mockListMessages,
  mockRetryMessage,
  mockSendMessage,
} from "./mock-messages";
import type {
  ChatMessageListData,
  MessageBranchData,
  MessageRetryData,
  RunData,
  StreamCancelData,
  StreamEndData,
  StreamStartData,
  StreamToolData,
} from "./types";

const useMock = import.meta.env.VITE_USE_MOCK === "true";

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

// ---------------------------------------------------------------------------
// SSE 流式
// ---------------------------------------------------------------------------

export interface StreamHandlers {
  onStart?: (data: StreamStartData) => void;
  onDelta?: (delta: string) => void;
  onTool?: (data: StreamToolData) => void;
  onEnd?: (data: StreamEndData) => void;
  onError?: (message: string) => void;
}

function parseFrame(frame: string): { event: string; data: string } {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  return { event, data: data.join("\n") };
}

function dispatch(frame: string, handlers: StreamHandlers): void {
  const { event, data } = parseFrame(frame);
  if (!data) return;
  const payload = JSON.parse(data);
  if (event === "message_start") handlers.onStart?.(payload as StreamStartData);
  else if (event === "part_delta") handlers.onDelta?.(String(payload.delta ?? ""));
  else if (event === "tool_call") handlers.onTool?.(payload as StreamToolData);
  else if (event === "message_end") handlers.onEnd?.(payload as StreamEndData);
  else if (event === "error") {
    handlers.onError?.(String(payload.message ?? "流式运行失败"));
  }
}

/**
 * 流式发送：POST /agents/run/stream，用 fetch + ReadableStream 读取 SSE。
 *
 * EventSource 无法带 Authorization 头，所以这里手动解析 text/event-stream。
 */
export async function streamMessage(
  sessionId: string,
  text: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  if (useMock) {
    const result = await mockSendMessage(sessionId, text);
    handlers.onDelta?.(String(result.output ?? ""));
    return;
  }

  const baseURL = import.meta.env.VITE_API_BASE || "/api/v1";
  const token = localStorage.getItem(TOKEN_KEY);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${baseURL}/agents/run/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ goal: text, mode: "single", conversation_id: sessionId }),
    signal,
  });

  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const body = await response.json();
      message = body?.message || body?.detail || message;
    } catch {
      // 非 JSON 错误响应，沿用状态码提示
    }
    throw new ApiError(String(response.status), message, response.status);
  }
  if (!response.body) throw new ApiError("empty", "响应体为空", 0);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let index = buffer.indexOf("\n\n");
    while (index >= 0) {
      const frame = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      if (frame.trim()) dispatch(frame, handlers);
      index = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) dispatch(buffer, handlers);
}

// ---------------------------------------------------------------------------
// 运行控制与消息派生
// ---------------------------------------------------------------------------

/** POST /agents/runs/{run_id}/cancel（协作式取消） */
export async function cancelStreamRun(runId: string): Promise<StreamCancelData> {
  if (useMock) return mockCancelStreamRun(runId);
  return post<StreamCancelData>(`/agents/runs/${runId}/cancel`);
}

/** POST /sessions/{id}/messages/{message_id}/retry（失败消息重试） */
export async function retryMessage(
  sessionId: string,
  messageId: string,
): Promise<MessageRetryData> {
  if (useMock) return mockRetryMessage(sessionId, messageId);
  return post<MessageRetryData>(
    `/sessions/${sessionId}/messages/${messageId}/retry`,
  );
}

/** POST /sessions/{id}/messages/{message_id}/branch（会话分支） */
export async function branchMessage(
  sessionId: string,
  messageId: string,
): Promise<MessageBranchData> {
  if (useMock) return mockBranchMessage(sessionId, messageId);
  return post<MessageBranchData>(
    `/sessions/${sessionId}/messages/${messageId}/branch`,
  );
}
