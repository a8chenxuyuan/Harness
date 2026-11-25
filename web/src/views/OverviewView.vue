/** 概览页：KPI + 最近会话 + 运行队列 / 系统健康。 */
<template>
  <div>
    <PageHeader title="概览" subtitle="最近 24 小时的运行与资源概况">
      <template #actions>
        <button class="btn ghost" @click="reload">刷新</button>
        <button class="btn primary" @click="router.push('/agent')">＋ 新建运行</button>
      </template>
    </PageHeader>

    <div class="kpi-grid">
      <StatCard label="今日运行" hint="24h" value="128" unit="次" delta="▲ 12.4% 环比" />
      <StatCard
        label="成功率"
        hint="24h"
        value="98.6"
        unit="%"
        delta="▲ 0.8% 环比"
        tone="ok"
        points="0,12 20,14 40,10 60,13 80,8 100,9 120,6 140,8 160,4"
      />
      <StatCard
        label="平均耗时"
        hint="P50"
        value="2.4"
        unit="s"
        delta="▼ 6.2% 环比"
        down
        tone="cyan"
        points="0,8 20,11 40,9 60,15 80,13 100,18 120,16 140,21 160,20"
      />
      <StatCard
        label="待审批计划"
        hint="HITL"
        value="3"
        unit="个"
        delta="● 需要处理"
        tone="warn"
        points="0,20 20,20 40,18 60,19 80,14 100,15 120,9 140,10 160,8"
      />
    </div>

    <div class="split">
      <div class="panel">
        <div class="panel-head">
          <h3>最近会话</h3>
          <span class="muted">按更新时间</span>
          <div class="seg">
            <button :class="{ on: filter === 'all' }" @click="filter = 'all'">全部</button>
            <button :class="{ on: filter === 'active' }" @click="filter = 'active'">进行中</button>
          </div>
        </div>

        <table class="table">
          <thead>
            <tr><th>会话</th><th>状态</th><th>消息</th><th>更新时间</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="5" class="loading">加载中…</td>
            </tr>
            <template v-else>
              <tr
                v-for="item in visible"
                :key="item.session_id"
                class="clickable"
                @click="router.push(`/sessions/${item.session_id}`)"
              >
              <td>
                <div class="cell-title">{{ item.title }}</div>
                <div class="cell-sub mono">{{ item.session_id }}</div>
              </td>
              <td>
                <span class="pill" :class="item.status === 'active' ? 'ok' : 'warn'">
                  <i></i>{{ item.status }}
                </span>
              </td>
                <td class="mono">{{ item.message_count }}</td>
                <td class="mono">{{ item.updated_at }}</td>
                <td>›</td>
              </tr>
            </template>
          </tbody>
        </table>
        <div class="foot">
          共 {{ total }} 个会话
          <span class="link" @click="router.push('/sessions')">查看全部 →</span>
        </div>
      </div>

      <div class="side-panel">
        <div class="panel mini">
          <h4>运行队列</h4>
          <p>2 个运行中 · 1 个排队中</p>
          <ul class="timeline">
            <li class="live"><b>订单超时分析</b><span>running · 8.4s</span></li>
            <li class="done"><b>周报汇总</b><span>completed · 2.1s</span></li>
            <li class="done"><b>代码评审</b><span>completed · 5.7s</span></li>
          </ul>
        </div>
        <div class="panel mini">
          <h4>系统健康</h4>
          <p>API / DB / 工具目录均正常</p>
          <ul class="timeline">
            <li class="done"><b>GET /ready</b><span>200 · 12ms</span></li>
            <li class="done"><b>数据库</b><span>connected</span></li>
            <li class="done"><b>工具目录</b><span>4 tools</span></li>
          </ul>
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
import StatCard from "@/components/StatCard.vue";
import { pushToast } from "@/composables/toast";

const router = useRouter();
const loading = ref(true);
const total = ref(0);
const sessions = ref<SessionSummary[]>([]);
const filter = ref<"all" | "active">("all");

const visible = computed(() => {
  const rows = filter.value === "active" ? sessions.value.filter((item) => item.status === "active") : sessions.value;
  return rows.slice(0, 4);
});

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const data = await listSessions(1, 6);
    sessions.value = data.items;
    total.value = data.total;
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "加载失败");
  } finally {
    loading.value = false;
  }
}

onMounted(reload);
</script>

<style scoped>
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.mini {
  padding: 14px 16px;
}

.mini h4 {
  margin: 0 0 3px;
  font-size: 12px;
  font-weight: 580;
}

.mini p {
  margin: 0;
  color: var(--faint);
  font-size: 11.5px;
}

.loading {
  text-align: center;
  color: var(--faint);
  padding: 24px;
}

.link {
  margin-left: auto;
  cursor: pointer;
}

.link:hover {
  color: var(--text);
}

@media (max-width: 1180px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
