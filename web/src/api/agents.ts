/** Agent 运行接口：提交 / 查状态 / 取消。 */
import { get, post } from "./http";
import type { RunData } from "./types";

/** POST /agents/run（同步执行，前端给足超时） */
export async function startRun(goal: string): Promise<RunData> {
  return post<RunData>("/agents/run", { goal, mode: "single" });
}

/** GET /agents/{run_id}/status */
export async function fetchRunStatus(runId: string): Promise<RunData> {
  return get<RunData>(`/agents/${runId}/status`);
}

/** POST /agents/{run_id}/cancel */
export async function cancelRun(runId: string): Promise<RunData> {
  return post<RunData>(`/agents/${runId}/cancel`);
}
