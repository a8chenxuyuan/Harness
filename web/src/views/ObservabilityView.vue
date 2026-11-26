/** 可观测页：HTTP 流量 / 错误率 / 延迟与最近错误，5 秒自动刷新。 */
<template>
  <div>
    <PageHeader title="可观测" subtitle="HTTP 流量、错误率与延迟（每 5 秒自动刷新）">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="reload()">刷新</button>
        <a class="btn primary" href="/metrics" target="_blank" rel="noopener">
          Prometheus /metrics
        </a>
      </template>
    </PageHeader>

    <div v-if="forbidden" class="panel forbidden">
      当前账号无权查看运行指标，请使用 owner / admin 账号登录。
    </div>

    <template v-else>
      <div class="metric-grid">
        <div class="metric-card">
          <span class="metric-label">总请求</span>
          <strong class="metric-value">{{ summary?.total_requests ?? 0 }}</strong>
          <em class="metric-hint">进程启动以来累计</em>
        </div>
        <div class="metric-card">
          <span class="metric-label">错误率</span>
          <strong class="metric-value" :class="{ bad: errorRate > 0.05 }">
            {{ errorRateText }}
          </strong>
          <em class="metric-hint">{{ summary?.error_requests ?? 0 }} 次 4xx / 5xx</em>
        </div>
        <div class="metric-card">
          <span class="metric-label">平均延迟</span>
          <strong class="metric-value">{{ avgText }}<small>ms</small></strong>
          <em class="metric-hint">近 500 次请求窗口</em>
        </div>
        <div class="metric-card">
          <span class="metric-label">P95 延迟</span>
          <strong class="metric-value">{{ p95Text }}<small>ms</small></strong>
          <em class="metric-hint">同窗口 95 分位</em>
        </div>
      </div>

      <div class="split">
        <div class="panel">
          <div class="panel-head">
            <h3>状态分布</h3>
            <span class="muted">2xx / 3xx / 4xx / 5xx</span>
          </div>
          <div class="bars">
            <div v-for="item in statusItems" :key="item.key" class="bar-row">
              <span class="bar-label">{{ item.label }}</span>
              <div class="bar-track">
                <div
                  class="bar-fill"
                  :class="item.tone"
                  :style="{ width: barWidth(item.value) }"
                ></div>
              </div>
              <span class="bar-value mono">{{ item.value }}</span>
            </div>
          </div>
          <div class="meta-line">
            <span>
              Prometheus：{{ summary?.prometheus_available ? "已接入" : "未安装（降级视图）" }}
            </span>
            <span>运行时长：{{ uptimeText }}</span>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h3>最近错误</h3>
            <span class="muted">最多 10 条</span>
          </div>
          <table class="table">
            <thead>
              <tr><th>时间</th><th>请求</th><th>状态</th><th>耗时</th><th>request_id</th></tr>
            </thead>
            <tbody>
              <tr v-if="!summary?.recent_errors.length">
                <td colspan="5" class="loading">暂无错误</td>
              </tr>
              <tr v-for="item in summary?.recent_errors" :key="item.request_id + item.time">
                <td class="mono nowrap">{{ formatTime(item.time) }}</td>
                <td class="mono">{{ item.method }} {{ item.path }}</td>
                <td><span class="pill err"><i></i>{{ item.status }}</span></td>
                <td class="mono">{{ item.duration_ms }} ms</td>
                <td class="mono ellipsis" :title="item.request_id">{{ item.request_id }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

import { ApiError } from "@/api/http";
import { fetchMetricsSummary } from "@/api/observability";
import type { MetricsSummary } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const REFRESH_MS = 5000;

const summary = ref<MetricsSummary | null>(null);
const loading = ref(true);
const forbidden = ref(false);
let timer: number | undefined;

const errorRate = computed(() => summary.value?.error_rate ?? 0);
const errorRateText = computed(() => `${(errorRate.value * 100).toFixed(2)}%`);
const avgText = computed(() => (summary.value?.avg_ms ?? 0).toFixed(1));
const p95Text = computed(() => (summary.value?.p95_ms ?? 0).toFixed(1));
const uptimeText = computed(() => formatDuration(summary.value?.uptime_seconds ?? 0));

const statusItems = computed(() => {
  const counts = summary.value?.status_counts;
  return [
    { key: "ok", label: "2xx", value: counts?.ok ?? 0, tone: "ok" },
    { key: "redirect", label: "3xx", value: counts?.redirect ?? 0, tone: "info" },
    { key: "client_error", label: "4xx", value: counts?.client_error ?? 0, tone: "warn" },
    { key: "server_error", label: "5xx", value: counts?.server_error ?? 0, tone: "err" },
  ];
});

async function reload(silent = false): Promise<void> {
  if (!silent) loading.value = true;
  try {
    summary.value = await fetchMetricsSummary();
    forbidden.value = false;
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      forbidden.value = true;
    } else if (!silent) {
      pushToast(err instanceof Error ? err.message : "指标加载失败");
    }
  } finally {
    loading.value = false;
  }
}

function barWidth(value: number): string {
  const total = summary.value?.total_requests ?? 0;
  if (!total || !value) return "0%";
  return `${Math.max(2, Math.round((value / total) * 100))}%`;
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString("zh-CN", { hour12: false });
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m ${total % 60}s`;
}

onMounted(() => {
  void reload();
  timer = window.setInterval(() => void reload(true), REFRESH_MS);
});

onUnmounted(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<style scoped src="./ObservabilityView.css"></style>
