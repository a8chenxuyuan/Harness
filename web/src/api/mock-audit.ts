/** 前端 mock 数据（审计日志）：列表 / 动作枚举 / CSV。 */
import { delay } from "./mock";
import type { AuditLogItem, AuditLogListData, AuditQuery } from "./types";

const ACTIONS = [
  "session.create",
  "message.append",
  "agent.run",
  "run.cancel",
  "message.retry",
  "message.branch",
  "session.archive",
  "tool.call",
];

const RESULTS = ["success", "success", "success", "success", "accepted", "error"];

/** 固定 26 条演示审计数据。 */
const auditLogs: AuditLogItem[] = Array.from({ length: 26 }, (_, index) => {
  const action = ACTIONS[index % ACTIONS.length];
  const result = RESULTS[index % RESULTS.length];
  return {
    id: 26 - index,
    user_id: index % 4 === 0 ? "u-admin" : "u-member",
    session_id: index % 3 === 0 ? null : `s-${(index + 1).toString(16).padStart(4, "0")}c4`,
    action,
    target: action.startsWith("session") ? `s-${(index + 1).toString(16)}` : action,
    result,
    detail: result === "error" ? { error: "模型调用超时" } : { source: "mock" },
    created_at: new Date(Date.now() - index * 37 * 60 * 1000).toISOString(),
  };
});

function filtered(params: AuditQuery): AuditLogItem[] {
  return auditLogs.filter((item) => {
    if (params.action && item.action !== params.action) return false;
    if (params.result && item.result !== params.result) return false;
    if (params.user_id && item.user_id !== params.user_id) return false;
    if (params.session_id && item.session_id !== params.session_id) return false;
    if (params.since && item.created_at < params.since) return false;
    if (params.until && item.created_at > params.until) return false;
    return true;
  });
}

export async function mockListAuditLogs(params: AuditQuery): Promise<AuditLogListData> {
  const page = params.page ?? 1;
  const size = params.size ?? 20;
  const rows = filtered(params);
  return delay({
    items: rows.slice((page - 1) * size, page * size),
    total: rows.length,
    page,
    size,
  }, 160);
}

export async function mockListAuditActions(): Promise<string[]> {
  return delay([...new Set(auditLogs.map((item) => item.action))].sort(), 90);
}

/** 生成与后端一致的 CSV 文本（含 BOM）。 */
export async function mockExportAuditLogs(
  params: AuditQuery,
): Promise<{ content: string; filename: string }> {
  const rows = filtered(params);
  const header = "时间,动作,结果,用户,会话,目标,详情";
  const lines = rows.map((item) =>
    [
      item.created_at,
      item.action,
      item.result,
      item.user_id,
      item.session_id ?? "",
      item.target,
      JSON.stringify(item.detail),
    ]
      .map(csvCell)
      .join(","),
  );
  return delay({
    content: `\ufeff${[header, ...lines].join("\r\n")}`,
    filename: `audit-logs-${Date.now()}.csv`,
  }, 120);
}

function csvCell(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}
