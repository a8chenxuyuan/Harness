<!-- OAuth 回调落地页：读取后端 302 带回的双 token，写入登录态后跳转。 -->
<template>
  <div class="oauth-callback">
    <div class="card">
      <template v-if="error">
        <h2>登录失败</h2>
        <p class="error">{{ error }}</p>
        <button class="btn primary" type="button" @click="router.push('/login')">
          返回登录
        </button>
      </template>
      <template v-else>
        <h2>登录成功，正在进入控制台…</h2>
        <p v-if="pending" class="pending">正在拉取用户信息…</p>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const error = ref("");
const pending = ref(true);

onMounted(async () => {
  const access = typeof route.query.access_token === "string" ? route.query.access_token : "";
  const refresh = typeof route.query.refresh_token === "string" ? route.query.refresh_token : "";
  if (!access || !refresh) {
    error.value =
      typeof route.query.error === "string" ? route.query.error : "缺少登录凭据";
    pending.value = false;
    return;
  }
  auth.adoptTokens(access, refresh);
  try {
    await auth.hydrate();
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    await router.replace(redirect.startsWith("/") ? redirect : "/");
  } catch {
    error.value = "登录态已写入，但拉取用户信息失败";
    pending.value = false;
  }
});
</script>

<style scoped>
.oauth-callback {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-muted);
}

.card {
  width: 360px;
  padding: 28px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  text-align: center;
}

.card h2 {
  margin: 0 0 10px;
  font-size: 16px;
}

.error {
  color: var(--err);
  font-size: 12.5px;
  margin: 0 0 14px;
}

.pending {
  color: var(--muted);
  font-size: 12.5px;
  margin: 0;
}
</style>
