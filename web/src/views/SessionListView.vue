/** 会话列表页：筛选 + 分页 + 行点击进详情。 */
<template>
  <div>
    <PageHeader title="会话" subtitle="当前账号下全部会话，按更新时间倒序">
      <template #actions>
        <button class="btn ghost" @click="reload">刷新</button>
        <button class="btn primary" @click="tip">＋ 新建会话</button>
      </template>
    </PageHeader>

    <div class="panel">
      <div class="panel-head">
        <h3>我的会话</h3>
        <span class="muted">{{ total }} 条 · 第 {{ page }} / {{ pages }} 页</span>
        <div class="seg">
          <button :class="{ on: filter === 'all' }" @click="setFilter('all')">全部</button>
          <button :class="{ on: filter === 'active' }" @click="setFilter('active')">active</button>
          <button :class="{ on: filter === 'archived' }" @click="setFilter('archived')">archived</button>
        </div>
      </div>

      <table class="table">
        <thead>
          <tr><th>会话</th><th>状态</th><th>消息数</th><th>会话 ID</th><th>最近更新</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="6" class="loading">加载中…</td>
          </tr>
          <tr v-else-if="rows.length === 0">
            <td colspan="6" class="loading">没有符合条件的会话</td>
          </tr>
          <template v-else>
            <tr
              v-for="item in rows"
              :key="item.session_id"
              class="clickable"
              @click="router.push(`/sessions/${item.session_id}`)"
            >
            <td>
              <div class="cell-title">{{ item.title }}</div>
              <div class="cell-sub">最近一条：{{ item.message_count }} 条消息</div>
            </td>
            <td>
              <span class="pill" :class="item.status === 'active' ? 'ok' : 'warn'"><i></i>{{ item.status }}</span>
            </td>
            <td class="mono">{{ item.message_count }}</td>
              <td class="mono">{{ item.session_id }}</td>
              <td class="mono">{{ item.updated_at }}</td>
              <td>›</td>
            </tr>
          </template>
        </tbody>
      </table>

      <div class="foot">
        共 {{ total }} 条 · 每页 {{ size }}
        <div class="pager">
          <span :class="{ disabled: page <= 1 }" @click="go(page - 1)">‹</span>
          <span v-for="p in pages" :key="p" :class="{ on: p === page }" @click="go(p)">{{ p }}</span>
          <span :class="{ disabled: page >= pages }" @click="go(page + 1)">›</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { listSessions } from "@/api/sessions";
import type { SessionSummary } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const router = useRouter();
const size = 8;
const page = ref(1);
const total = ref(0);
const items = ref<SessionSummary[]>([]);
const filter = ref<"all" | "active" | "archived">("all");
const loading = ref(true);

const pages = computed(() => Math.max(1, Math.ceil(total.value / size)));
const rows = computed(() =>
  filter.value === "all" ? items.value : items.value.filter((item) => item.status === filter.value),
);

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const data = await listSessions(page.value, size);
    items.value = data.items;
    total.value = data.total;
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "加载失败");
  } finally {
    loading.value = false;
  }
}

function go(target: number): void {
  if (target < 1 || target > pages.value) return;
  page.value = target;
  void reload();
}

function setFilter(next: "all" | "active" | "archived"): void {
  filter.value = next;
}

function tip(): void {
  pushToast("新建会话接口待接入（样板阶段）");
}

onMounted(reload);
</script>

<style scoped>
.loading {
  text-align: center;
  color: var(--faint);
  padding: 24px;
}

.pager {
  margin-left: auto;
  display: flex;
  gap: 5px;
}

.pager span {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 3px 8px;
  background: var(--surface-2);
  cursor: pointer;
}

.pager span.on {
  border-color: var(--accent);
  color: #c7c9ff;
}

.pager span.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
