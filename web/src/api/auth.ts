/** 认证接口：登录 / 当前用户。 */
import { get, post } from "./http";
import type { LoginData, UserInfo } from "./types";

export type { LoginData, UserInfo } from "./types";

/** POST /auth/login */
export async function login(username: string, password: string): Promise<LoginData> {
  return post<LoginData>("/auth/login", { username, password });
}

/** GET /auth/me */
export async function fetchMe(): Promise<UserInfo> {
  return get<UserInfo>("/auth/me");
}
