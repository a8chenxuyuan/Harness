/** 任务中心接口（W4.1-WEB-02）：运行记录的用户视角封装。 */
import { get } from "./http";
import type { RunItem } from "./types";

/** GET /runs：分页列当前用户任务（时间倒序）。 */
export async function listRuns(
  page = 1,
  size = 20,
  status?: string,
): Promise<{ items: RunItem[]; total: number; page: number; size: number }> {
  const params: Record<string, unknown> = { page, size };
  if (status) params.status = status;
  return get("/runs", params);
}

/** GET /runs/{id}：任务详情（时间线数据源）。 */
export async function getRun(runId: string): Promise<RunItem> {
  return get<RunItem>(`/runs/${runId}`);
}
