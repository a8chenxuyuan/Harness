/** 会话接口：列表 / 详情 / 新建 / 删除。 */
import { del, get, post } from "./http";
import { mockCreateSession, mockGetSession, mockListSessions } from "./mock";
import type { SessionDetail, SessionListData } from "./types";

const useMock = import.meta.env.VITE_USE_MOCK !== "false";

/** POST /sessions */
export async function createSession(title = ""): Promise<SessionDetail> {
  if (useMock) return mockCreateSession(title);
  return post<SessionDetail>("/sessions", { title });
}

/** GET /sessions?page=&size= */
export async function listSessions(page = 1, size = 20): Promise<SessionListData> {
  if (useMock) return mockListSessions(page, size);
  return get<SessionListData>("/sessions", { page, size });
}

/** GET /sessions/{id} */
export async function getSession(sessionId: string): Promise<SessionDetail> {
  if (useMock) return mockGetSession(sessionId);
  return get<SessionDetail>(`/sessions/${sessionId}`);
}

/** DELETE /sessions/{id} */
export async function removeSession(sessionId: string): Promise<void> {
  if (useMock) return;
  await del<unknown>(`/sessions/${sessionId}`);
}
