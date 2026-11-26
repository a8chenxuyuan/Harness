/** 审计接口：列表 / 动作枚举 / CSV 导出（owner / admin）。 */
import { get, http } from "./http";
import type { AuditLogListData, AuditQuery } from "./types";

/** GET /audit-logs */
export async function listAuditLogs(params: AuditQuery): Promise<AuditLogListData> {
  return get<AuditLogListData>("/audit-logs", params as Record<string, unknown>);
}

/** GET /audit-logs/actions */
export async function listAuditActions(): Promise<string[]> {
  return get<string[]>("/audit-logs/actions");
}

/** GET /audit-logs/export：按当前过滤条件下载 CSV。 */
export async function exportAuditLogs(params: AuditQuery): Promise<void> {
  const response = await http.get<Blob>("/audit-logs/export", {
    params,
    responseType: "blob",
  });
  const disposition = String(response.headers["content-disposition"] ?? "");
  const matched = disposition.match(/filename="?([^";]+)"?/);
  saveBlob(response.data, matched?.[1] ?? "audit-logs.csv");
}

/** 触发浏览器下载。 */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
