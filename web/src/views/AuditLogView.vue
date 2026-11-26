/** 审计日志页：多条件过滤 + 分页 + CSV 导出（owner / admin）。 */
<template>
  <div>
    <PageHeader title="审计日志" subtitle="租户内关键操作的只读记录，支持过滤与 CSV 导出">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="reload">刷新</button>
        <button class="btn primary" :disabled="exporting || forbidden" @click="download">
          {{ exporting ? "导出中…" : "导出 CSV" }}
        </button>
      </template>
    </PageHeader>

    <div class="panel">
      <div class="filters">
        <label>
          <span>动作</span>
          <select v-model="filters.action">
            <option value="">全部</option>
            <option v-for="item in actions" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <label>
          <span>结果</span>
          <select v-model="filters.result">
            <option value="">全部</option>
            <option value="success">success</option>
            <option value="accepted">accepted</option>
            <option value="denied">denied</option>
            <option value="error">error</option>
          </select>
        </label>
        <label>
          <span>用户</span>
          <input v-model.trim="filters.user_id" placeholder="user id" />
        </label>
        <label>
          <span>会话</span>
          <input v-model.trim="filters.session_id" placeholder="session id" />
        </label>
        <label>
          <span>开始</span>
          <input v-model="filters.since" type="datetime-local" />
        </label>
        <label>
          <span>结束</span>
          <input v-model="filters.until" type="datetime-local" />
        </label>
        <div class="filter-actions">
          <button class="btn ghost" @click="reset">重置</button>
          <button class="btn primary" @click="search">查询</button>
        </div>
      </div>

      <div v-if="forbidden" class="empty">
        当前账号无权查看审计日志，请使用 owner / admin 账号登录。
      </div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>时间</th><th>动作</th><th>结果</th><th>用户</th>
            <th>会话</th><th>目标</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="7" class="empty">加载中…</td>
          </tr>
          <tr v-else-if="items.length === 0">
            <td colspan="7" class="empty">没有符合条件的记录</td>
          </tr>
          <template v-else v-for="item in items" :key="item.id">
            <tr class="clickable" @click="toggle(item.id)">
              <td class="mono nowrap">{{ formatTime(item.created_at) }}</td>
              <td class="mono">{{ item.action }}</td>
              <td>
                <span class="pill" :class="resultClass(item.result)"><i></i>{{ item.result }}</span>
              </td>
              <td class="mono">{{ item.user_id }}</td>
              <td class="mono ellipsis">{{ item.session_id || "—" }}</td>
              <td class="mono ellipsis" :title="item.target">{{ item.target || "—" }}</td>
              <td class="row-hint">{{ expanded === item.id ? "收起" : "详情" }}</td>
            </tr>
            <tr v-if="expanded === item.id">
              <td colspan="7" class="detail-cell">
                <pre class="detail">{{ pretty(item.detail) }}</pre>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <div class="foot">
        共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页
        <div class="pager">
          <span :class="{ disabled: page <= 1 }" @click="go(page - 1)">‹</span>
          <span class="on">{{ page }}</span>
          <span :class="{ disabled: page >= pages }" @click="go(page + 1)">›</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { exportAuditLogs, listAuditActions, listAuditLogs } from "@/api/audit";
import { ApiError } from "@/api/http";
import type { AuditLogItem, AuditQuery } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const size = 20;
const page = ref(1);
const total = ref(0);
const items = ref<AuditLogItem[]>([]);
const actions = ref<string[]>([]);
const loading = ref(true);
const exporting = ref(false);
const forbidden = ref(false);
const expanded = ref<number | null>(null);

const filters = reactive({
  action: "",
  result: "",
  user_id: "",
  session_id: "",
  since: "",
  until: "",
});

const pages = computed(() => Math.max(1, Math.ceil(total.value / size)));

/** 组装查询参数；导出时不含分页。 */
function buildQuery(withPage: boolean): AuditQuery {
  const params: AuditQuery = {};
  if (filters.action) params.action = filters.action;
  if (filters.result) params.result = filters.result;
  if (filters.user_id) params.user_id = filters.user_id;
  if (filters.session_id) params.session_id = filters.session_id;
  if (filters.since) params.since = new Date(filters.since).toISOString();
  if (filters.until) params.until = new Date(filters.until).toISOString();
  if (withPage) {
    params.page = page.value;
    params.size = size;
  }
  return params;
}

async function reload(): Promise<void> {
  loading.value = true;
  forbidden.value = false;
  try {
    const data = await listAuditLogs(buildQuery(true));
    items.value = data.items;
    total.value = data.total;
    expanded.value = null;
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      forbidden.value = true;
      items.value = [];
      total.value = 0;
    } else {
      pushToast(err instanceof Error ? err.message : "加载失败");
    }
  } finally {
    loading.value = false;
  }
}

async function loadActions(): Promise<void> {
  try {
    actions.value = await listAuditActions();
  } catch {
    // 无权访问时由 reload 统一展示提示，这里静默
  }
}

async function search(): Promise<void> {
  page.value = 1;
  await reload();
}

function reset(): void {
  filters.action = "";
  filters.result = "";
  filters.user_id = "";
  filters.session_id = "";
  filters.since = "";
  filters.until = "";
  void search();
}

function go(target: number): void {
  if (target < 1 || target > pages.value || target === page.value) return;
  page.value = target;
  void reload();
}

async function download(): Promise<void> {
  exporting.value = true;
  try {
    await exportAuditLogs(buildQuery(false));
    pushToast("导出已开始");
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "导出失败");
  } finally {
    exporting.value = false;
  }
}

function toggle(id: number): void {
  expanded.value = expanded.value === id ? null : id;
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function pretty(detail: Record<string, unknown>): string {
  return JSON.stringify(detail, null, 2);
}

function resultClass(result: string): string {
  if (result === "success") return "ok";
  if (result === "accepted") return "info";
  if (result === "denied") return "warn";
  return "err";
}

onMounted(() => {
  void loadActions();
  void reload();
});
</script>

<style scoped src="./AuditLogView.css"></style>
