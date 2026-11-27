<template>
  <div class="page">
    <!-- 员工欢迎卡 -->
    <section class="hero">
      <div class="hero-avatar">小</div>
      <div class="hero-text">
        <h1>你好 👋</h1>
        <p>我是你的数字化员工「小哈」，随时帮你处理消息、任务与跨平台事务。</p>
      </div>
      <button class="primary-btn" @click="goChat">开始对话</button>
    </section>

    <!-- 快捷指令 -->
    <section class="section">
      <h2 class="section-title">快捷指令</h2>
      <div class="commands">
        <button v-for="cmd in commands" :key="cmd.label" class="cmd" @click="goChat">
          <span class="cmd-ico">{{ cmd.icon }}</span>
          <span>
            <b>{{ cmd.label }}</b>
            <small>{{ cmd.desc }}</small>
          </span>
        </button>
      </div>
    </section>

    <div class="cols">
      <!-- 今日摘要（数据接入后由 CHAN-06 提供真实数据） -->
      <section class="section">
        <h2 class="section-title">今日摘要</h2>
        <div class="card summary">
          <div class="summary-row">
            <span>企业微信未读消息</span>
            <b class="muted">待接入</b>
          </div>
          <div class="summary-row">
            <span>跨平台待办</span>
            <b class="muted">待接入</b>
          </div>
          <p class="summary-note">
            连接企业微信后，这里会自动汇总你各平台的消息与待办。
            <RouterLink to="/connections">去连接 →</RouterLink>
          </p>
        </div>
      </section>

      <!-- 最近任务 -->
      <section class="section">
        <h2 class="section-title">最近任务</h2>
        <div class="card">
          <div v-if="recentTasks.length" class="task-rows">
            <div v-for="t in recentTasks" :key="t.run_id" class="task-row" @click="goTasks">
              <span class="badge" :class="statusClass(t.status)">{{ statusLabel(t.status) }}</span>
              <span class="task-goal">{{ taskGoal(t) }}</span>
              <small>{{ shortTime(t.created_at) }}</small>
            </div>
          </div>
          <p v-else class="empty">还没有任务记录，去 <RouterLink to="/sessions">对话</RouterLink> 给员工下达第一个任务吧。</p>
          <RouterLink v-if="recentTasks.length" class="more" to="/tasks">查看全部任务 →</RouterLink>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";

import { listRuns } from "@/api/runs";
import type { RunItem } from "@/api/types";

const router = useRouter();

const commands = [
  { icon: "✉", label: "汇总未读消息", desc: "把各平台未读聚合成一份简报" },
  { icon: "✎", label: "帮我回复", desc: "起草并代发一条回复" },
  { icon: "◎", label: "日程与待办", desc: "看看今天还有什么要做" },
];

const recentTasks = ref<RunItem[]>([]);

function taskGoal(t: RunItem): string {
  const goal = t.input?.goal ?? t.input?.message ?? t.input?.task;
  return typeof goal === "string" && goal ? goal.slice(0, 40) : t.run_id.slice(0, 8);
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
  if (!iso) return "";
  return iso.slice(5, 16).replace("T", " ");
}

function goChat(): void {
  void router.push("/sessions");
}

function goTasks(): void {
  void router.push("/tasks");
}

onMounted(async () => {
  try {
    const resp = await listRuns(1, 5);
    recentTasks.value = resp.items;
  } catch {
    /* 摘要失败不打扰首页 */
  }
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 22px;
}
.hero {
  display: flex;
  align-items: center;
  gap: 18px;
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  border-radius: 14px;
  padding: 22px 24px;
}
.hero-avatar {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: var(--accent, #5b8cff);
  color: #fff;
  font-size: 24px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.hero-text h1 {
  margin: 0 0 4px;
  font-size: 20px;
}
.hero-text p {
  margin: 0;
  color: var(--text-muted, #8b93a7);
  font-size: 13px;
}
.primary-btn {
  margin-left: auto;
  background: var(--accent, #5b8cff);
  border: none;
  color: #fff;
  border-radius: 10px;
  padding: 10px 20px;
  font-size: 14px;
  cursor: pointer;
}
.section-title {
  margin: 0 0 10px;
  font-size: 15px;
}
.commands {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.cmd {
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  border-radius: 12px;
  padding: 14px 16px;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
}
.cmd:hover {
  border-color: var(--accent, #5b8cff);
}
.cmd small {
  display: block;
  color: var(--text-muted, #8b93a7);
  font-size: 12px;
}
.cmd-ico {
  font-size: 18px;
}
.cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.card {
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  border-radius: 12px;
  padding: 14px 16px;
}
.summary-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  font-size: 13px;
  border-bottom: 1px dashed var(--border, #262c3a);
}
.muted {
  color: var(--text-muted, #8b93a7);
}
.summary-note {
  margin: 10px 0 0;
  color: var(--text-muted, #8b93a7);
  font-size: 12px;
}
.task-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  font-size: 13px;
  cursor: pointer;
  border-bottom: 1px dashed var(--border, #262c3a);
}
.task-goal {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.badge {
  border-radius: 999px;
  padding: 1px 9px;
  font-size: 12px;
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
.more {
  display: inline-block;
  margin-top: 10px;
  font-size: 13px;
}
.empty {
  color: var(--text-muted, #8b93a7);
  font-size: 13px;
  margin: 6px 0 0;
}
</style>
