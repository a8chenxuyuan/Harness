/** 会话接口：列表 / 详情 / 新建 / 归档 / 删除。 */
import { del, get, post } from "./http";
import type { SessionDetail, SessionListData } from "./types";

/** POST /sessions */
export async function createSession(title = ""): Promise<SessionDetail> {
  return post<SessionDetail>("/sessions", { title });
}

/** GET /sessions?page=&size=&status= */
export async function listSessions(
  page = 1,
  size = 20,
  status?: string,
): Promise<SessionListData> {
  const params: Record<string, unknown> = { page, size };
  if (status && status !== "all") params.status = status;
  return get<SessionListData>("/sessions", params);
}

/** GET /sessions/{id} */
export async function getSession(sessionId: string): Promise<SessionDetail> {
  return get<SessionDetail>(`/sessions/${sessionId}`);
}

/** POST /sessions/{id}/archive|unarchive */
export async function archiveSession(
  sessionId: string,
  archived = true,
): Promise<SessionDetail> {
  return post<SessionDetail>(
    `/sessions/${sessionId}/${archived ? "archive" : "unarchive"}`,
  );
}

/** DELETE /sessions/{id} */
export async function removeSession(sessionId: string): Promise<void> {
  await del<unknown>(`/sessions/${sessionId}`);
}
