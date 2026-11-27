/** 权限管理接口（W4.1-WEB-01）：页面矩阵 + 用户角色分配。 */
import { get, put } from "./http";
import type { PermissionUser } from "./types";

/** 权限管理页的用户行（类型定义在 ./types，此处转发导出）。 */
export type { PermissionUser };
/** 角色 × 页面矩阵。 */
export interface MatrixData {
  pages: string[];
  roles: string[];
  matrix: Record<string, Record<string, boolean>>;
  default_matrix: Record<string, string[]>;
}

/** GET /permissions/matrix */
export async function fetchMatrix(): Promise<MatrixData> {
  return get<MatrixData>("/permissions/matrix");
}

/** PUT /permissions/matrix：改单格。 */
export async function updateMatrixEntry(
  role: string,
  pageKey: string,
  allowed: boolean,
): Promise<void> {
  await put<unknown>("/permissions/matrix", { role, page_key: pageKey, allowed });
}

/** GET /permissions/users */
export async function fetchPermissionUsers(): Promise<PermissionUser[]> {
  const resp = await get<{ items: PermissionUser[] }>("/permissions/users");
  return resp.items;
}

/** PUT /permissions/users/{id}/roles：全量替换角色列表。 */
export async function updateUserRoles(
  userId: string,
  roles: string[],
): Promise<{ user_id: string; roles: string[]; primary_role: string }> {
  return put<{ user_id: string; roles: string[]; primary_role: string }>(
    `/permissions/users/${userId}/roles`,
    { roles },
  );
}
