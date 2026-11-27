<template>
  <div class="page">
    <header class="page-head">
      <h1>我的连接</h1>
      <p class="sub">管理已授权的平台账号；连接后员工才能替你收发消息、汇总信息。</p>
    </header>

    <div v-if="bindings.length" class="grid">
      <div v-for="b in bindings" :key="b.id" class="conn">
        <div class="conn-head">
          <span class="plat">{{ platformLabel(b.platform) }}</span>
          <span class="badge" :class="b.status === 'active' ? 'ok' : 'muted'">
            {{ b.status === "active" ? "已连接" : b.status }}
          </span>
        </div>
        <div class="conn-body">
          <div class="kv"><span class="k">账号</span><span>{{ b.display_name || b.platform_user_id }}</span></div>
          <div class="kv"><span class="k">绑定时间</span><span>{{ shortTime(b.created_at) }}</span></div>
          <div class="kv"><span class="k">最近登录</span><span>{{ shortTime(b.last_login_at) }}</span></div>
        </div>
        <button class="danger-btn" @click="onRevoke(b)">断开连接</button>
      </div>
    </div>
    <div v-else class="empty-card">
      <p>还没有连接任何平台。</p>
    </div>

    <section class="card add">
      <h2>添加连接</h2>
      <div class="add-row">
        <div class="add-item">
          <b>企业微信</b>
          <small>扫码登录即可自动建立连接</small>
          <RouterLink class="link" to="/login">去登录页扫码 →</RouterLink>
        </div>
        <div class="add-item disabled">
          <b>飞书</b>
          <small>即将支持</small>
        </div>
        <div class="add-item disabled">
          <b>钉钉</b>
          <small>即将支持</small>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { fetchBindings, revokeBinding } from "@/api/connections";
import type { ChannelBinding } from "@/api/types";
import { pushToast } from "@/composables/toast";

const bindings = ref<ChannelBinding[]>([]);

function platformLabel(platform: string): string {
  const map: Record<string, string> = {
    wecom: "企业微信",
    feishu: "飞书",
    dingtalk: "钉钉",
  };
  return map[platform] ?? platform;
}

function shortTime(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

async function onRevoke(b: ChannelBinding): Promise<void> {
  if (!window.confirm(`确定断开 ${platformLabel(b.platform)} 的连接吗？断开后该平台消息将不再路由给你。`)) {
    return;
  }
  try {
    await revokeBinding(b.id);
    bindings.value = bindings.value.filter((x) => x.id !== b.id);
    pushToast("已断开连接");
  } catch (err) {
    pushToast(`断开失败：${err instanceof Error ? err.message : "未知错误"}`);
  }
}

onMounted(async () => {
  try {
    bindings.value = await fetchBindings();
  } catch (err) {
    pushToast(`加载失败：${err instanceof Error ? err.message : "未知错误"}`);
  }
});
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
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.conn {
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.conn-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.plat {
  font-size: 15px;
  font-weight: 600;
}
.badge {
  border-radius: 999px;
  padding: 1px 10px;
  font-size: 12px;
}
.badge.ok {
  background: rgba(60, 170, 110, 0.15);
  color: #4caf7d;
}
.badge.muted {
  background: var(--surface-muted, #1d2230);
  color: var(--text-muted, #8b93a7);
}
.kv {
  display: flex;
  gap: 12px;
  font-size: 13px;
  padding: 2px 0;
}
.k {
  color: var(--text-muted, #8b93a7);
  flex-shrink: 0;
  width: 64px;
}
.danger-btn {
  align-self: flex-start;
  background: transparent;
  border: 1px solid rgba(220, 90, 90, 0.5);
  color: #e07a7a;
  border-radius: 8px;
  padding: 5px 14px;
  font-size: 13px;
  cursor: pointer;
}
.danger-btn:hover {
  background: rgba(220, 90, 90, 0.1);
}
.card {
  background: var(--surface, #141821);
  border: 1px solid var(--border, #262c3a);
  border-radius: 12px;
  padding: 16px 18px;
}
.card h2 {
  margin: 0 0 12px;
  font-size: 15px;
}
.add-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.add-item {
  border: 1px dashed var(--border, #262c3a);
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.add-item small {
  color: var(--text-muted, #8b93a7);
}
.add-item.disabled {
  opacity: 0.55;
}
.link {
  color: var(--accent, #7ba1ff);
  font-size: 13px;
}
.empty-card {
  background: var(--surface, #141821);
  border: 1px dashed var(--border, #262c3a);
  border-radius: 12px;
  padding: 28px;
  text-align: center;
  color: var(--text-muted, #8b93a7);
}
</style>
