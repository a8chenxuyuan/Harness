/** axios 封装：统一响应解包、Bearer 注入、错误归一化。 */
import axios, { AxiosError } from "axios";

import type { ApiResponse } from "./types";

export const TOKEN_KEY = "harness.access_token";

/** 后端错误或网络错误统一包装。 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || "/api/v1",
  // /agents/run 是同步执行，超时给足
  timeout: 120_000,
});

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

interface ErrorPayload {
  code?: string | number;
  message?: string;
  detail?: unknown;
}

http.interceptors.response.use(undefined, (error: AxiosError<ErrorPayload>) => {
  const status = error.response?.status ?? 0;
  if (status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem("harness.refresh_token");
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  const payload = error.response?.data;
  return Promise.reject(
    new ApiError(
      String(payload?.code ?? status),
      payload?.message || error.message || "网络异常",
      status,
    ),
  );
});

/** 拆包并校验 code。 */
function unwrap<T>(body: ApiResponse<T>): T {
  if (body && typeof body === "object" && "code" in body) {
    if (body.code !== 0) {
      throw new ApiError(String(body.code), body.message || "请求失败", 200);
    }
    return body.data;
  }
  return body as unknown as T;
}

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await http.get<ApiResponse<T>>(url, params ? { params } : undefined);
  return unwrap(response.data);
}

export async function post<T>(url: string, body?: unknown): Promise<T> {
  const response = await http.post<ApiResponse<T>>(url, body);
  return unwrap(response.data);
}

export async function del<T>(url: string): Promise<T> {
  const response = await http.delete<ApiResponse<T>>(url);
  return unwrap(response.data);
}

export async function patch<T>(url: string, body?: unknown): Promise<T> {
  const response = await http.patch<ApiResponse<T>>(url, body);
  return unwrap(response.data);
}

export async function put<T>(url: string, body?: unknown): Promise<T> {
  const response = await http.put<ApiResponse<T>>(url, body);
  return unwrap(response.data);
}
