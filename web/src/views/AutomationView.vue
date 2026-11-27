<template>
  <div class="page">
    <header class="page-head">
      <h1>自动化</h1>
      <p class="sub">把重复的事交给员工：定时任务、跨平台转发、主动提醒。</p>
    </header>

    <section class="hero-card">
      <div class="ico">⚙</div>
      <div>
        <h2>自动化配方即将上线</h2>
        <p>
          届时你可以像搭积木一样配置：
          <b>触发器</b>（每天 9 点 / 收到某人消息 / 收到审批）→
          <b>动作</b>（跑 Agent 任务 / 跨平台转发 / 企微通知我）。
        </p>
        <p class="hint">当前版本已支持对话与任务执行；配方引擎在 W4.1-WEB-03 交付。</p>
      </div>
    </section>

    <section class="examples">
      <div class="example">
        <b>早上 9 点推送摘要</b>
        <small>员工把各平台未读消息汇总成简报，经企业微信发给你</small>
      </div>
      <div class="example">
        <b>重要消息跨平台转发</b>
        <small>收到指定联系人的消息时，第一时间转发到你的微信</small>
      </div>
      <div class="example">
        <b>审批进度提醒</b>
        <small>审批状态变化时自动通知你，不用一直盯着</small>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
/* 占位页：自动化配方引擎在 W4.1-WEB-03 实现 */
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
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
.hero-card {
  display: flex;
  gap: 16px;
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  border-radius: 12px;
  padding: 20px 22px;
}
.hero-card .ico {
  font-size: 26px;
}
.hero-card h2 {
  margin: 0 0 6px;
  font-size: 16px;
}
.hero-card p {
  margin: 0 0 4px;
  color: var(--text-muted, #8b93a7);
  font-size: 13px;
  line-height: 1.6;
}
.hint {
  font-size: 12px;
}
.examples {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.example {
  background: var(--surface, #141821);
  border: 1px dashed var(--border, #262c3a);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.example small {
  color: var(--text-muted, #8b93a7);
}
</style>
