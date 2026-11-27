/** 登录态 store：token 持久化到 localStorage，用户信息按需拉取。 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { fetchMe, login as loginApi, type UserInfo } from "@/api/auth";

const TOKEN_KEY = "harness.access_token";
const REFRESH_KEY = "harness.refresh_token";

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) ?? "");
  const refreshToken = ref(localStorage.getItem(REFRESH_KEY) ?? "");
  const user = ref<UserInfo | null>(null);
  const loading = ref(false);

  const loggedIn = computed(() => Boolean(token.value));

  /** 可见页面（多角色并集）；未拉取前视为空（路由守卫放行到 hydrate）。 */
  const allowedPages = computed<string[]>(() => user.value?.allowed_pages ?? []);

  /** 登录：写入 token 后拉一次 /auth/me。 */
  async function signIn(username: string, password: string): Promise<void> {
    loading.value = true;
    try {
      const data = await loginApi(username, password);
      token.value = data.access_token;
      refreshToken.value = data.refresh_token;
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem(REFRESH_KEY, data.refresh_token);
      user.value = await fetchMe();
    } finally {
      loading.value = false;
    }
  }

  /** 退出：清空本地登录态。 */
  function signOut(): void {
    token.value = "";
    refreshToken.value = "";
    user.value = null;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  }

  /** 刷新页面后恢复用户信息；失败则视为未登录。 */
  async function hydrate(): Promise<void> {
    if (!token.value || user.value) return;
    try {
      user.value = await fetchMe();
    } catch {
      signOut();
    }
  }

  /** OAuth 免密登录采纳：直接写入后端签发的双 token。 */
  function adoptTokens(access: string, refresh: string): void {
    token.value = access;
    refreshToken.value = refresh;
    localStorage.setItem(TOKEN_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  }

  return {
    token,
    refreshToken,
    user,
    loading,
    loggedIn,
    allowedPages,
    signIn,
    signOut,
    hydrate,
    adoptTokens,
  };
});
