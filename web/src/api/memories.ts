/** Memory 管理 API 封装（W4-02）。

后端接口见 src/harness/platform/api/controllers/memories.py。
所有方法返回解包后的 data（code=0 时），错误抛 ApiError。
*/

import { del, get, post } from "./http";
import type {
  MemoryListData,
  MemorySaveBody,
  MemorySaveData,
} from "./types";

interface ListParams {
  keyword?: string;
  limit?: number;
  offset?: number;
  session_id?: string | null;
}

/** GET /memories —— 分页查询，支持关键词搜索 + session 筛选。 */
export function listMemories(params: ListParams = {}): Promise<MemoryListData> {
  return get<MemoryListData>("/memories", params as Record<string, unknown>);
}

/** POST /memories —— 手动保存一条长期记忆。用户主动存的不需要审核。 */
export function saveMemory(body: MemorySaveBody): Promise<MemorySaveData> {
  return post<MemorySaveData>("/memories", body);
}

/** DELETE /memories/{item_id} —— 删除记忆。 */
export function deleteMemory(itemId: string): Promise<{ deleted: boolean }> {
  return del<{ deleted: boolean }>(`/memories/${encodeURIComponent(itemId)}`);
}
