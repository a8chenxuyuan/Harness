/** Agent 运行页：提交目标 → 轮询状态 → 展示时间线与输出。 */
<template>
  <div>
    <PageHeader title="Agent 运行" subtitle="提交目标 → 执行 → 轮询状态，失败可读错误">
      <template #actions>
        <span v-if="run" class="pill info mono run-id">{{ run.run_id }}</span>
        <button class="btn danger" :disabled="!running" @click="cancel">取消运行</button>
      </template>
    </PageHeader>

    <div class="split">
      <div class="panel">
        <div class="panel-head"><h3>目标</h3><span class="muted">goal</span></div>
        <div class="composer">
          <textarea v-model="goal" rows="4" placeholder="描述你希望 Agent 完成的目标…"></textarea>
          <div class="chips">
            <span v-for="chip in chips" :key="chip" class="chip" @click="appendChip(chip)">{{ chip }}</span>
          </div>
          <div class="run-actions">
            <button class="btn primary" :disabled="running || !goal.trim()" @click="start">
              {{ running ? "运行中…" : "▶ 开始运行" }}
            </button>
            <button class="btn ghost" @click="tip('编排模式接口待接入')">编排模式 coordinator</button>
          </div>
        </div>

        <div class="panel-head output-head">
          <h3>输出</h3>
          <span class="muted">{{ statusText }}</span>
        </div>
        <pre class="output">{{ outputText }}</pre>
      </div>

      <div class="side-panel">
        <div class="panel mini">
          <h4>执行时间线</h4>
          <p>POST /agents/run → GET /agents/{id}/status</p>
          <ul class="timeline">
            <li :class="stepClass(0)"><b>已提交</b><span>{{ timeText(0) }}</span></li>
            <li :class="stepClass(1)"><b>模型已选择</b><span>{{ timeText(1) }}</span></li>
            <li :class="stepClass(2)"><b>工具执行</b><span>{{ timeText(2) }}</span></li>
            <li :class="stepClass(3)"><b>汇总输出</b><span>{{ timeText(3) }}</span></li>
          </ul>
        </div>
        <div class="panel mini">
          <h4>指标</h4>
          <p>来自响应 metrics 字段</p>
          <ul class="timeline">
            <li class="done"><b>tokens</b><span>{{ run?.metrics?.tokens ?? "—" }}</span></li>
            <li class="done"><b>工具调用</b><span>{{ run?.metrics?.tool_calls ?? "—" }}</span></li>
            <li class="done"><b>耗时</b><span>{{ elapsedText }}</span></li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

import { cancelRun, fetchRunStatus, startRun } from "@/api/agents";
import type { RunData } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const chips = ["读取订单表", "按渠道分组", "生成三条建议"];
const goal = ref("统计上周订单超时原因，按渠道分组给出结论，并给出三条可执行的改进建议。");
const run = ref<RunData | null>(null);
const running = ref(false);
const startedAt = ref(0);
const now = ref(0);
const timings = ref<string[]>(["", "", "", ""]);

let pollTimer = 0;
let tickTimer = 0;

const statusText = computed(() => {
  if (!run.value) return "未运行";
  if (run.value.status === "running") return `running · ${elapsedText.value}`;
  return `${run.value.status} · ${elapsedText.value}`;
});

const elapsedText = computed(() => {
  if (!run.value) return "—";
  const elapsed = run.value.metrics?.elapsed_ms;
  if (typeof elapsed === "number") return `${(elapsed / 1000).toFixed(1)}s`;
  if (!startedAt.value) return "—";
  return `${((now.value - startedAt.value) / 1000).toFixed(1)}s`;
});

const outputText = computed(() => {
  if (!run.value) {
    return '{\n  "hint": "输入目标后点击「开始运行」"\n}';
  }
  if (run.value.error) {
    return JSON.stringify({ run_id: run.value.run_id, status: run.value.status, error: run.value.error }, null, 2);
  }
  return JSON.stringify(run.value, null, 2);
});

/** 时间线步骤样式：index 0-3。 */
function stepClass(index: number): string {
  if (!run.value) return "";
  const status = run.value.status;
  if (status === "running") return index < 2 ? "done" : index === 2 ? "live" : "";
  if (status === "completed") return "done";
  return index === 0 ? "done" : "";
}

function timeText(index: number): string {
  return timings.value[index] || "pending";
}

/** 启动一次运行并开始轮询。 */
async function start(): Promise<void> {
  running.value = true;
  timings.value = ["", "", "", ""];
  startedAt.value = Date.now();
  now.value = startedAt.value;
  try {
    run.value = await startRun(goal.value);
    timings.value[0] = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    beginPolling();
  } catch (err) {
    running.value = false;
    pushToast(err instanceof Error ? err.message : "提交失败");
  }
}

function beginPolling(): void {
  stopTimers();
  tickTimer = window.setInterval(() => {
    now.value = Date.now();
  }, 100);
  pollTimer = window.setInterval(async () => {
    if (!run.value) return;
    try {
      const next = await fetchRunStatus(run.value.run_id);
      run.value = next;
      if (next.status === "running") {
        timings.value[1] = timings.value[1] || new Date().toLocaleTimeString("zh-CN", { hour12: false });
        timings.value[2] = timings.value[2] || "tool: read_file";
      } else {
        timings.value[2] = "4 tools";
        timings.value[3] = new Date().toLocaleTimeString("zh-CN", { hour12: false });
        running.value = false;
        stopTimers();
        pushToast(next.status === "completed" ? "运行完成" : `运行结束：${next.status}`);
      }
    } catch (err) {
      running.value = false;
      stopTimers();
      pushToast(err instanceof Error ? err.message : "轮询失败");
    }
  }, 600);
}

function stopTimers(): void {
  if (pollTimer) window.clearInterval(pollTimer);
  if (tickTimer) window.clearInterval(tickTimer);
  pollTimer = 0;
  tickTimer = 0;
}

async function cancel(): Promise<void> {
  if (!run.value) return;
  try {
    run.value = await cancelRun(run.value.run_id);
    running.value = false;
    stopTimers();
    timings.value[3] = "cancelled";
    pushToast("已取消");
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "取消失败");
  }
}

function appendChip(text: string): void {
  goal.value = `${goal.value.replace(/\s+$/, "")}，${text}`;
}

function tip(text: string): void {
  pushToast(text);
}

onBeforeUnmount(stopTimers);
</script>

<style scoped>
.run-id {
  padding: 5px 10px;
}

.composer {
  padding: 14px 16px;
}

.composer textarea {
  width: 100%;
  min-height: 84px;
  resize: vertical;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--text);
  padding: 11px 12px;
  font-size: 12.5px;
  font-family: inherit;
  line-height: 1.6;
  outline: none;
}

.composer textarea:focus {
  border-color: rgba(99, 102, 241, 0.6);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 9px;
}

.chip {
  font-size: 11px;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 9px;
  background: var(--surface-2);
  cursor: pointer;
}

.chip:hover {
  color: var(--text);
  border-color: var(--muted);
}

.run-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.output-head {
  border-top: 1px solid var(--line-soft);
}

.output {
  margin: 0;
  background: #05060a;
  border-top: 1px solid var(--line-soft);
  padding: 14px 16px;
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.8;
  color: #c9d1e0;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
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
</style>
