/** 工具市场 / MCP 注册 API 封装（W4-EXT-02）。

后端接口见 src/harness/platform/api/controllers/tools.py 与 mcp.py。
所有方法返回解包后的 data（code=0 时），错误抛 ApiError。
*/

import { del, get, post } from "./http";
import type {
  McpServerListData,
  McpServerRegisterBody,
  ToolDebugData,
  ToolMarketData,
} from "./types";

/** GET /tools/market —— 内置 + MCP 工具聚合市场（含来源标注）。 */
export function listToolMarket(): Promise<ToolMarketData> {
  return get<ToolMarketData>("/tools/market");
}

/** POST /tools/{name}/debug —— 调试执行一个只读工具（写类会被后端 403 拒绝）。 */
export function debugTool(name: string, arguments_: Record<string, unknown>): Promise<ToolDebugData> {
  return post<ToolDebugData>(`/tools/${encodeURIComponent(name)}/debug`, { arguments: arguments_ });
}

/** GET /mcp/servers —— 列出已注册的 MCP server。 */
export function listMcpServers(): Promise<McpServerListData> {
  return get<McpServerListData>("/mcp/servers");
}

/** POST /mcp/servers —— 注册外部 MCP server（握手失败 502，重名 409）。 */
export function registerMcpServer(body: McpServerRegisterBody): Promise<{ server: import("./types").McpServerItem }> {
  return post<{ server: import("./types").McpServerItem }>("/mcp/servers", body);
}

/** DELETE /mcp/servers/{name} —— 注销 server 并回收其工具。 */
export function deleteMcpServer(name: string): Promise<{ deleted: boolean }> {
  return del<{ deleted: boolean }>(`/mcp/servers/${encodeURIComponent(name)}`);
}
