<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>权限管理</h1>
        <p class="sub">配置角色可见页面与用户角色分配；owner 永远全量可见（保底）。</p>
      </div>
    </header>

    <!-- 角色 × 页面矩阵 -->
    <section class="card">
      <div class="card-head">
        <h2>页面可见性矩阵</h2>
        <span class="hint">改动即时生效；owner 行不可修改</span>
      </div>
      <table v-if="matrix" class="matrix">
        <thead>
          <tr>
            <th class="page-col">页面</th>
            <th v-for="role in matrix.roles" :key="role">{{ role }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="page in matrix.pages" :key="page">
            <td class="page-col">{{ pageLabel(page) }}</td>
            <td v-for="role in matrix.roles" :key="role" class="cell">
              <input
                type="checkbox"
                :checked="matrix.matrix[role]?.[page]"
                :disabled="role === 'owner' || saving"
                @change="onToggle(role, page, ($event.target as HTMLInputElement).checked)"
              />
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">加载中…</div>
    </section>

    <!-- 用户角色分配 -->
    <section class="card">
      <div class="card-head">
        <h2>用户角色分配</h2>
        <span class="hint">一人可挂多个角色，页面权限取并集</span>
      </div>
      <table v-if="users.length" class="users">
        <thead>
          <tr>
            <th>用户</th>
            <th>主角色</th>
            <th>角色（多选）</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.user_id">
            <td>
              <b>{{ u.username }}</b>
              <small>{{ u.email }}</small>
            </td>
            <td><span class="badge">{{ u.primary_role }}</span></td>
            <td class="roles-cell">
              <label v-for="role in assignable" :key="role" class="role-chip">
                <input
                  type="checkbox"
                  :checked="u.roles.includes(role)"
                  :disabled="saving"
                  @change="onRoleChange(u, role, ($event.target as HTMLInputElement).checked)"
                />
                {{ role }}
              </label>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">加载中…</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";

import { pushToast } from "@/composables/toast";
import {
  fetchMatrix,
  fetchPermissionUsers,
  updateMatrixEntry,
  updateUserRoles,
  type MatrixData,
} from "@/api/permissions";
import type { PermissionUser } from "@/api/types";

const matrix = ref<MatrixData | null>(null);
const users = ref<PermissionUser[]>([]);
const saving = ref(false);
const assignable = ["owner", "admin", "member"];

const PAGE_LABELS: Record<string, string> = {
  overview: "概览",
  sessions: "会话",
  agent: "Agent 运行",
  skills: "Skill 管理",
  memories: "长期记忆",
  tools: "工具市场",
  "api-keys": "API Key",
  webhooks: "Webhooks",
  plans: "计划",
  worker: "Worker",
  audit: "审计日志",
  observability: "可观测",
  settings: "设置",
  permissions: "权限管理",
};

function pageLabel(key: string): string {
  return PAGE_LABELS[key] ?? key;
}

/** 改单格矩阵（乐观更新，失败回滚并提示）。 */
async function onToggle(role: string, page: string, allowed: boolean): Promise<void> {
  if (!matrix.value) return;
  saving.value = true;
  try {
    await updateMatrixEntry(role, page, allowed);
    if (matrix.value.matrix[role]) matrix.value.matrix[role][page] = allowed;
    pushToast(`已更新：${role} · ${pageLabel(page)} → ${allowed ? "可见" : "隐藏"}`);
  } catch (err) {
    pushToast(`更新失败：${err instanceof Error ? err.message : "未知错误"}`);
    matrix.value.matrix[role][page] = !allowed;
  } finally {
    saving.value = false;
  }
}

/** 用户角色勾选变化：全量替换该用户角色列表。 */
async function onRoleChange(u: PermissionUser, role: string, checked: boolean): Promise<void> {
  const next = checked
    ? [...new Set([...u.roles, role])]
    : u.roles.filter((r) => r !== role);
  if (next.length === 0) {
    pushToast("至少保留一个角色");
    u.roles = [...u.roles];
    return;
  }
  saving.value = true;
  try {
    const data = await updateUserRoles(u.user_id, next);
    u.roles = [...data.roles].sort();
    u.primary_role = data.primary_role;
    pushToast(`已更新 ${u.username} 的角色：${u.roles.join(" + ")}`);
  } catch (err) {
    pushToast(`分配失败：${err instanceof Error ? err.message : "未知错误"}`);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  try {
    const [m, list] = await Promise.all([fetchMatrix(), fetchPermissionUsers()]);
    matrix.value = m;
    users.value = list;
  } catch (err) {
    pushToast(`加载失败：${err instanceof Error ? err.message : "未知错误"}`);
  }
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.page-head h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.sub {
  margin: 0;
  color: var(--text-muted, #8b93a7);
  font-size: 13px;
}
.card {
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  border-radius: 12px;
  padding: 18px 20px;
}
.card-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 14px;
}
.card-head h2 {
  margin: 0;
  font-size: 16px;
}
.hint {
  color: var(--text-muted, #8b93a7);
  font-size: 12px;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border, #262c3a);
  text-align: left;
  font-size: 13px;
}
th {
  color: var(--text-muted, #8b93a7);
  font-weight: 600;
}
.page-col {
  width: 160px;
}
.cell {
  text-align: center;
}
.cell input,
.role-chip input {
  accent-color: var(--accent, #5b8cff);
}
.users td small {
  display: block;
  color: var(--text-muted, #8b93a7);
}
.roles-cell {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.role-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
}
.badge {
  background: var(--surface-muted, #1d2230);
  border: 1px solid var(--border, #262c3a);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
}
.empty {
  color: var(--text-muted, #8b93a7);
  padding: 20px 0;
  text-align: center;
}
</style>
