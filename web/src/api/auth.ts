/** 认证接口：登录 / 当前用户。 */
import { post, get } from "./http";
import { mockLogin, mockMe } from "./mock";
import type { LoginData, UserInfo } from "./types";

export type { LoginData, UserInfo } from "./types";

const useMock = import.meta.env.VITE_USE_MOCK !== "false";

/** POST /auth/login */
export async function login(username: string, password: string): Promise<LoginData> {
  if (useMock) return mockLogin(username, password);
  return post<LoginData>("/auth/login", { username, password });
}

/** GET /auth/me */
export async function fetchMe(): Promise<UserInfo> {
  if (useMock) return mockMe();
  return get<UserInfo>("/auth/me");
}
