/** 路由表：登录独立，其余页面共用 AppShell 布局；meta.pageKey 用于页面权限（W4.1-WEB-01）。 */
import { createRouter, createWebHistory } from "vue-router";

import AppShell from "@/layout/AppShell.vue";
import { useAuthStore } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { public: true, title: "登录" },
    },
    {
      path: "/oauth/callback",
      name: "oauth-callback",
      component: () => import("@/views/OAuthCallbackView.vue"),
      meta: { public: true, title: "OAuth 登录" },
    },
    {
      path: "/",
      component: AppShell,
      children: [
        {
          path: "",
          name: "home",
          component: () => import("@/views/WorkbenchView.vue"),
          meta: { title: "工作台", pageKey: "home" },
        },
        {
          path: "overview",
          name: "overview",
          component: () => import("@/views/OverviewView.vue"),
          meta: { title: "概览", pageKey: "overview" },
        },
        {
          path: "tasks",
          name: "tasks",
          component: () => import("@/views/TasksView.vue"),
          meta: { title: "任务中心", pageKey: "tasks" },
        },
        {
          path: "automation",
          name: "automation",
          component: () => import("@/views/AutomationView.vue"),
          meta: { title: "自动化", pageKey: "automation" },
        },
        {
          path: "connections",
          name: "connections",
          component: () => import("@/views/ConnectionsView.vue"),
          meta: { title: "我的连接", pageKey: "connections" },
        },
        {
          path: "sessions",
          name: "sessions",
          component: () => import("@/views/SessionListView.vue"),
          meta: { title: "会话", pageKey: "sessions" },
        },
        {
          path: "sessions/:id",
          name: "session-detail",
          component: () => import("@/views/SessionDetailView.vue"),
          meta: { title: "会话详情", pageKey: "sessions" },
        },
        {
          path: "agent",
          name: "agent",
          component: () => import("@/views/AgentRunView.vue"),
          meta: { title: "Agent 运行", pageKey: "agent" },
        },
        {
          path: "audit",
          name: "audit",
          component: () => import("@/views/AuditLogView.vue"),
          meta: { title: "审计日志", pageKey: "audit" },
        },
        {
          path: "observability",
          name: "observability",
          component: () => import("@/views/ObservabilityView.vue"),
          meta: { title: "可观测", pageKey: "observability" },
        },
        {
          path: "skills",
          name: "skills",
          component: () => import("@/views/SkillListView.vue"),
          meta: { title: "Skill 管理", pageKey: "skills" },
        },
        {
          path: "memories",
          name: "memories",
          component: () => import("@/views/MemoryListView.vue"),
          meta: { title: "长期记忆", pageKey: "memories" },
        },
        {
          path: "tools",
          name: "tools",
          component: () => import("@/views/ToolMarketView.vue"),
          meta: { title: "工具市场", pageKey: "tools" },
        },
        {
          path: "api-keys",
          name: "api-keys",
          component: () => import("@/views/ApiKeysView.vue"),
          meta: { title: "API Key", pageKey: "api-keys" },
        },
        {
          path: "webhooks",
          name: "webhooks",
          component: () => import("@/views/WebhooksView.vue"),
          meta: { title: "Webhooks", pageKey: "webhooks" },
        },
        {
          path: "permissions",
          name: "permissions",
          component: () => import("@/views/PermissionsView.vue"),
          meta: { title: "权限管理", pageKey: "permissions" },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

/** 未登录回登录页；已登录但无该页权限回概览（W4.1-WEB-01 页面权限守卫）。 */
router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (to.meta.public) return true;
  if (!auth.loggedIn) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  // 刷新后首次导航先 hydrate（拉 /auth/me 拿 allowed_pages）
  if (!auth.user) await auth.hydrate();
  const pageKey = to.meta.pageKey as string | undefined;
  if (pageKey && auth.allowedPages.length > 0 && !auth.allowedPages.includes(pageKey)) {
    return { name: "overview" };
  }
  return true;
});

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? "控制台")} · Harness Console`;
});

export default router;
