/** 应用外壳：侧边导航 + 顶栏 + 内容区。 */
<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark"></div>
        <div class="brand-name">Harness<small>Agent Runtime</small></div>
      </div>

      <div class="ws">
        <div>
          <b>{{ tenant }}</b>
          <br />
          <span>{{ auth.user?.role ?? "member" }} · {{ auth.user?.user_id ?? "—" }}</span>
        </div>
        <span>⌄</span>
      </div>

      <div class="nav-label">我的空间</div>
      <RouterLink v-if="can('home')" class="nav-item" :class="{ active: isActive('home') }" to="/">
        <span class="ico">◫</span>工作台
      </RouterLink>
      <RouterLink v-if="can('sessions')" class="nav-item" :class="{ active: isActive('sessions') }" to="/sessions">
        <span class="ico">☰</span>对话
      </RouterLink>
      <RouterLink v-if="can('tasks')" class="nav-item" :class="{ active: isActive('tasks') }" to="/tasks">
        <span class="ico">☑</span>任务中心
      </RouterLink>
      <RouterLink v-if="can('automation')" class="nav-item" :class="{ active: isActive('automation') }" to="/automation">
        <span class="ico">⚡</span>自动化
      </RouterLink>
      <RouterLink v-if="can('connections')" class="nav-item" :class="{ active: isActive('connections') }" to="/connections">
        <span class="ico">⇄</span>我的连接
      </RouterLink>
      <RouterLink v-if="can('memories')" class="nav-item" :class="{ active: isActive('memories') }" to="/memories">
        <span class="ico">◇</span>员工记忆
      </RouterLink>

      <div v-if="hasAny(['overview', 'agent', 'skills', 'tools', 'api-keys', 'webhooks', 'audit', 'observability', 'permissions'])" class="nav-label">管理端</div>
      <RouterLink v-if="can('overview')" class="nav-item" :class="{ active: isActive('overview') }" to="/overview">
        <span class="ico">◫</span>概览
      </RouterLink>
      <RouterLink v-if="can('agent')" class="nav-item" :class="{ active: isActive('agent') }" to="/agent">
        <span class="ico">▶</span>Agent 运行
      </RouterLink>
      <RouterLink v-if="can('skills')" class="nav-item" :class="{ active: isActive('skills') }" to="/skills">
        <span class="ico">✦</span>Skill 管理
      </RouterLink>
      <RouterLink v-if="can('tools')" class="nav-item" :class="{ active: isActive('tools') }" to="/tools">
        <span class="ico">◫</span>工具市场
      </RouterLink>
      <RouterLink v-if="can('api-keys')" class="nav-item" :class="{ active: isActive('api-keys') }" to="/api-keys">
        <span class="ico">⌗</span>API Key
      </RouterLink>
      <RouterLink v-if="can('webhooks')" class="nav-item" :class="{ active: isActive('webhooks') }" to="/webhooks">
        <span class="ico">⇅</span>Webhooks
      </RouterLink>
      <RouterLink
        v-if="can('audit')"
        class="nav-item"
        :class="{ active: isActive('audit') }"
        to="/audit"
      >
        <span class="ico">▤</span>审计日志
      </RouterLink>
      <RouterLink
        v-if="can('observability')"
        class="nav-item"
        :class="{ active: isActive('observability') }"
        to="/observability"
      >
        <span class="ico">◎</span>可观测
      </RouterLink>
      <RouterLink
        v-if="can('permissions')"
        class="nav-item"
        :class="{ active: isActive('permissions') }"
        to="/permissions"
      >
        <span class="ico">⛨</span>权限管理
      </RouterLink>
      <div class="nav-item" @click="notReady('设置')"><span class="ico">⚙</span>设置</div>

      <div class="side-foot">
        <div class="user-row" @click="signOut">
          <div class="avatar">{{ initials }}</div>
          <div>
            <b>{{ auth.user?.user_id ?? "未登录" }}</b>
            <small>{{ auth.user?.role ?? "—" }} · 点击退出</small>
          </div>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="crumbs">Harness <span>/</span> <b>{{ title }}</b></div>
        <div class="search" @click="paletteOpen = true">
          ⌕ 搜索会话、运行、页面<span class="kbd">⌘K</span>
        </div>
        <button class="icon-btn" title="切换主题" @click="toggleTheme">◐</button>
        <button class="icon-btn" title="通知" @click="notReady('通知')">◔</button>
        <div class="avatar">{{ initials }}</div>
      </header>

      <div class="content">
        <RouterView />
      </div>
    </div>

    <CommandPalette :open="paletteOpen" @close="paletteOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import CommandPalette from "@/components/CommandPalette.vue";
import { pushToast } from "@/composables/toast";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const paletteOpen = ref(false);
const theme = ref(localStorage.getItem("harness.theme") ?? "dark");

const title = computed(() => String(route.meta.title ?? "概览"));
const tenant = computed(() => auth.user?.tenant_id ?? "dev-tenant");
const initials = computed(() => (auth.user?.user_id ?? "NA").slice(0, 2).toUpperCase());
/** 页面权限（W4.1-WEB-01）：allowed_pages 未拉取时放行（守卫负责 hydrate）。 */
function can(pageKey: string): boolean {
  const pages = auth.allowedPages;
  return pages.length === 0 || pages.includes(pageKey);
}

/** 分组下是否有任一可见页（决定分组标题显隐）。 */
function hasAny(pageKeys: string[]): boolean {
  return pageKeys.some((key) => can(key));
}

/** 当前导航项是否命中（详情页高亮"会话"）。 */
function isActive(name: string): boolean {
  if (name === "sessions") return route.name === "sessions" || route.name === "session-detail";
  return route.name === name;
}

function toggleTheme(): void {
  theme.value = theme.value === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme.value;
  localStorage.setItem("harness.theme", theme.value);
}

function signOut(): void {
  auth.signOut();
  void router.push({ name: "login" });
}

function notReady(name: string): void {
  pushToast(`${name} 页面尚未实现（样板阶段）`);
}

function onKeydown(event: KeyboardEvent): void {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    paletteOpen.value = !paletteOpen.value;
  }
  if (event.key === "Escape") paletteOpen.value = false;
}

onMounted(() => {
  document.documentElement.dataset.theme = theme.value;
  window.addEventListener("keydown", onKeydown);
  void auth.hydrate();
});

onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 248px;
  flex: none;
  position: sticky;
  top: 0;
  height: 100vh;
  background: var(--surface);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  padding: 14px 12px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px 14px;
}

.brand-mark {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  flex: none;
  background: conic-gradient(from 210deg, #6366f1, #22d3ee, #a78bfa, #6366f1);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18), 0 6px 18px -6px rgba(99, 102, 241, 0.9);
}

.brand-name {
  font-weight: 650;
  letter-spacing: 0.2px;
}

.brand-name small {
  display: block;
  font-weight: 400;
  color: var(--faint);
  font-size: 11px;
}

.ws {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px;
  margin-bottom: 16px;
  cursor: default;
}

.ws b {
  font-weight: 550;
  font-size: 12px;
}

.ws span {
  color: var(--faint);
  font-size: 11px;
}

.nav-label {
  color: var(--faint);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 10px 10px 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 9px;
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
  border: 1px solid transparent;
  transition: 0.16s;
}

.nav-item:hover {
  background: var(--surface-2);
  color: var(--text);
}

.nav-item.active {
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.18), rgba(99, 102, 241, 0.08));
  border-color: rgba(99, 102, 241, 0.35);
  color: #c7c9ff;
}

:global(html[data-theme="light"]) .nav-item.active {
  color: #4338ca;
}

.ico {
  width: 15px;
  text-align: center;
  opacity: 0.85;
}

.side-foot {
  margin-top: auto;
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.user-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 8px;
  border-radius: 10px;
  cursor: pointer;
}

.user-row:hover {
  background: var(--surface-2);
}

.avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  flex: none;
  background: linear-gradient(135deg, #6366f1, #22d3ee);
  color: #fff;
  font-size: 11px;
  font-weight: 650;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-row b {
  display: block;
  font-size: 12px;
  font-weight: 550;
}

.user-row small {
  color: var(--faint);
  font-size: 11px;
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  height: 56px;
  flex: none;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 22px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  backdrop-filter: blur(14px);
  position: sticky;
  top: 0;
  z-index: 20;
}

.crumbs {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--faint);
}

.crumbs b {
  color: var(--text);
  font-weight: 550;
}

.search {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--faint);
  border-radius: 9px;
  padding: 6px 9px;
  min-width: 220px;
  cursor: pointer;
  font-size: 12px;
}

.kbd {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 1px 5px;
  color: var(--muted);
}

.icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
}

.icon-btn:hover {
  color: var(--text);
  border-color: var(--muted);
}

.content {
  padding: 26px 26px 60px;
  max-width: 1480px;
  width: 100%;
  margin: 0 auto;
}

@media (max-width: 1180px) {
  .sidebar {
    width: 210px;
  }
}
</style>
