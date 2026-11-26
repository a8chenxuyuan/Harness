/** API Key 管理 API 封装（W4-API-01）。

后端接口见 src/harness/platform/api/controllers/apikeys.py。
机器调用侧鉴权：Authorization: Bearer hk_...（deps 按前缀分流）。
*/

import { del, get, post } from "./http";
import type { ApiKeyCreateBody, ApiKeyCreateData, ApiKeyListData } from "./types";

/** POST /api-keys —— 签发新 key；明文只在本次响应出现，请立即保存。 */
export function createApiKey(body: ApiKeyCreateBody): Promise<ApiKeyCreateData> {
  return post<ApiKeyCreateData>("/api-keys", body);
}

/** GET /api-keys —— 列出租户下全部 key（脱敏）。 */
export function listApiKeys(): Promise<ApiKeyListData> {
  return get<ApiKeyListData>("/api-keys");
}

/** DELETE /api-keys/{id} —— 吊销一个 key（幂等）。 */
export function revokeApiKey(id: string): Promise<{ revoked: boolean }> {
  return del<{ revoked: boolean }>(`/api-keys/${encodeURIComponent(id)}`);
}
