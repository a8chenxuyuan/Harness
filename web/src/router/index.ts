/** 路由表：登录独立，其余页面共用 AppShell 布局。 */
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
      path: "/",
      component: AppShell,
      children: [
        {
          path: "",
          name: "overview",
          component: () => import("@/views/OverviewView.vue"),
          meta: { title: "概览" },
        },
        {
          path: "sessions",
          name: "sessions",
          component: () => import("@/views/SessionListView.vue"),
          meta: { title: "会话" },
        },
        {
          path: "sessions/:id",
          name: "session-detail",
          component: () => import("@/views/SessionDetailView.vue"),
          meta: { title: "会话详情" },
        },
        {
          path: "agent",
          name: "agent",
          component: () => import("@/views/AgentRunView.vue"),
          meta: { title: "Agent 运行" },
        },
        {
          path: "audit",
          name: "audit",
          component: () => import("@/views/AuditLogView.vue"),
          meta: { title: "审计日志" },
        },
        {
          path: "observability",
          name: "observability",
          component: () => import("@/views/ObservabilityView.vue"),
          meta: { title: "可观测" },
        },
        {
          path: "skills",
          name: "skills",
          component: () => import("@/views/SkillListView.vue"),
          meta: { title: "Skill 管理" },
        },
        {
          path: "memories",
          name: "memories",
          component: () => import("@/views/MemoryListView.vue"),
          meta: { title: "长期记忆" },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

/** 未登录一律回登录页，并带上回跳地址。 */
router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.meta.public) return true;
  if (!auth.loggedIn) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  return true;
});

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? "控制台")} · Harness Console`;
});

export default router;
