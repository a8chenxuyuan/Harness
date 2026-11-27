<template>
  <div class="page">
    <header class="page-head">
      <h1>任务中心</h1>
      <p class="sub">员工执行过的所有任务：状态、结果与耗时一目了然。</p>
    </header>

    <div class="filters">
      <button
        v-for="f in filters"
        :key="f.value"
        class="chip"
        :class="{ active: current === f.value }"
        @click="switchFilter(f.value)"
      >
        {{ f.label }}
      </button>
    </div>

    <div v-if="error" class="empty">{{ error }}</div>
    <div v-else-if="!tasks.length && !loading" class="empty">还没有任务，去对话页给员工下达任务吧。</div>

    <div v-else class="list">
      <div v-for="t in tasks" :key="t.run_id" class="task" @click="toggleDetail(t.run_id)">
        <div class="task-main">
          <span class="badge" :class="statusClass(t.status)">{{ statusLabel(t.status) }}</span>
          <span class="goal">{{ taskGoal(t) }}</span>
          <small class="time">{{ shortTime(t.created_at) }}</small>
        </div>
        <div v-if="openId === t.run_id" class="detail" @click.stop>
          <div class="kv"><span class="k">任务 ID</span><span>{{ t.run_id }}</span></div>
          <div class="kv"><span class="k">模式</span><span>{{ t.mode }}</span></div>
          <div class="kv"><span class="k">开始 / 结束</span><span>{{ shortTime(t.started_at) }} → {{ shortTime(t.finished_at) || "—" }}</span></div>
          <div class="kv"><span class="k">Token 用量</span><span>{{ tokenText(t) }}</span></div>
          <template v-if="t.output">
            <div class="k block">执行结果</div>
            <pre class="pre">{{ t.output }}</pre>
          </template>
          <template v-if="t.error">
            <div class="k block">错误信息</div>
            <pre class="pre bad">{{ t.error }}</pre>
          </template>
        </div>
      </div>
    </div>

    <button v-if="hasMore" class="load" :disabled="loading" @click="loadMore">
      {{ loading ? "加载中…" : "加载更多" }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { listRuns } from "@/api/runs";
import type { RunItem } from "@/api/types";

const filters = [
  { label: "全部", value: "" },
  { label: "进行中", value: "running" },
  { label: "已完成", value: "succeeded" },
  { label: "失败", value: "failed" },
];

const tasks = ref<RunItem[]>([]);
const total = ref(0);
const page = ref(1);
const current = ref("");
const loading = ref(false);
const error = ref("");
const openId = ref("");

const hasMore = computed(() => tasks.value.length < total.value);

function taskGoal(t: RunItem): string {
  const goal = t.input?.goal ?? t.input?.message ?? t.input?.task;
  return typeof goal === "string" && goal ? goal : t.run_id;
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    queued: "排队中",
    running: "进行中",
    succeeded: "已完成",
    failed: "失败",
    cancelled: "已取消",
    paused: "已暂停",
    interrupted: "已中断",
  };
  return map[status] ?? status;
}

function statusClass(status: string): string {
  if (status === "succeeded") return "ok";
  if (status === "failed" || status === "cancelled") return "bad";
  return "run";
}

function shortTime(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

function tokenText(t: RunItem): string {
  const usage = t.token_usage ?? {};
  const keys = ["total_tokens", "total", "totalToken"];
  for (const k of keys) {
    const v = usage[k];
    if (typeof v === "number") return String(v);
  }
  return Object.keys(usage).length ? JSON.stringify(usage) : "—";
}

function toggleDetail(runId: string): void {
  openId.value = openId.value === runId ? "" : runId;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const resp = await listRuns(page.value, 20, current.value || undefined);
    if (page.value === 1) tasks.value = resp.items;
    else tasks.value = [...tasks.value, ...resp.items];
    total.value = resp.total;
  } catch (err) {
    error.value = `加载失败：${err instanceof Error ? err.message : "未知错误"}`;
  } finally {
    loading.value = false;
  }
}

function switchFilter(value: string): void {
  current.value = value;
  page.value = 1;
  void load();
}

function loadMore(): void {
  page.value += 1;
  void load();
}

onMounted(load);
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
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
.filters {
  display: flex;
  gap: 8px;
}
.chip {
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  color: inherit;
  border-radius: 999px;
  padding: 5px 14px;
  font-size: 13px;
  cursor: pointer;
}
.chip.active {
  border-color: var(--accent, #5b8cff);
  color: var(--accent, #7ba1ff);
}
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.task {
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  border-radius: 12px;
  padding: 12px 16px;
  cursor: pointer;
}
.task:hover {
  border-color: var(--accent, #5b8cff);
}
.task-main {
  display: flex;
  align-items: center;
  gap: 12px;
}
.goal {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.time {
  color: var(--text-muted, #8b93a7);
  font-size: 12px;
}
.badge {
  border-radius: 999px;
  padding: 1px 9px;
  font-size: 12px;
  flex-shrink: 0;
}
.badge.ok {
  background: rgba(60, 170, 110, 0.15);
  color: #4caf7d;
}
.badge.bad {
  background: rgba(220, 90, 90, 0.15);
  color: #e07a7a;
}
.badge.run {
  background: rgba(91, 140, 255, 0.15);
  color: #7ba1ff;
}
.detail {
  margin-top: 10px;
  border-top: 1px dashed var(--border, #262c3a);
  padding-top: 10px;
  font-size: 13px;
}
.kv {
  display: flex;
  gap: 12px;
  padding: 3px 0;
}
.k {
  color: var(--text-muted, #8b93a7);
  flex-shrink: 0;
}
.k.block {
  padding-top: 8px;
}
.pre {
  background: var(--surface-muted, #1d2230);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}
.pre.bad {
  color: #e07a7a;
}
.load {
  align-self: center;
  background: transparent;
  border: 1px solid var(--border, #262c3a);
  color: inherit;
  border-radius: 999px;
  padding: 6px 18px;
  font-size: 13px;
  cursor: pointer;
}
.empty {
  color: var(--text-muted, #8b93a7);
  font-size: 13px;
  text-align: center;
  padding: 30px 0;
}
</style>
