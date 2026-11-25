/** 登录页：左侧品牌 Hero，右侧表单。 */
<template>
  <div class="login">
    <div class="login-hero">
      <div>
        <div class="hero-tag">Harness · Agent Runtime</div>
        <h1 class="hero-title">把 Agent 的运行<br /><em>装进一个控制台</em></h1>
        <p class="hero-sub">
          会话、计划、Worker、沙箱与审计，全部收敛到同一处。左侧导航即工作流：从目标到执行，再到可观测。
        </p>
        <div class="hero-stats">
          <div><b>25</b><span>API 端点</span></div>
          <div><b>4</b><span>内置工具</span></div>
          <div><b>100%</b><span>评测通过</span></div>
        </div>
      </div>
      <div class="hero-foot">Harness Console · 样板版本</div>
    </div>

    <div class="login-form-wrap">
      <form class="login-form" @submit.prevent="submit">
        <h2>登录控制台</h2>
        <p>使用租户账号继续</p>

        <div class="field">
          <label>用户名 / 邮箱</label>
          <input v-model.trim="username" autocomplete="username" placeholder="admin" />
        </div>
        <div class="field">
          <label>密码</label>
          <input v-model="password" type="password" autocomplete="current-password" placeholder="admin123" />
        </div>

        <div class="form-row">
          <label class="remember"><input v-model="remember" type="checkbox" /> 记住我</label>
          <a href="#" @click.prevent="tip('忘记密码功能待接入')">忘记密码</a>
        </div>

        <p v-if="error" class="error">{{ error }}</p>

        <button class="btn primary submit" type="submit" :disabled="auth.loading">
          {{ auth.loading ? "登录中…" : "登录" }}
        </button>

        <div class="login-sep">或</div>
        <button class="btn ghost full" type="button" @click="tip('飞书登录待接入')">使用飞书账号登录</button>

        <div class="demo-hint">
          当前为 mock 模式，任意非空账号密码均可登录。<br />
          接真实后端：把 <code>VITE_USE_MOCK</code> 改为 <code>false</code>。
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { pushToast } from "@/composables/toast";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const username = ref("admin");
const password = ref("admin123");
const remember = ref(true);
const error = ref("");

/** 提交登录，成功后回到来源页。 */
async function submit(): Promise<void> {
  error.value = "";
  try {
    await auth.signIn(username.value, password.value);
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    await router.push(redirect);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "登录失败";
  }
}

function tip(text: string): void {
  pushToast(text);
}
</script>

<style scoped>
.login {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(380px, 0.9fr);
}

.login-hero {
  position: relative;
  overflow: hidden;
  padding: 54px 56px;
  background:
    radial-gradient(900px 420px at 12% 8%, rgba(99, 102, 241, 0.28), transparent 60%),
    radial-gradient(700px 380px at 88% 92%, rgba(34, 211, 238, 0.18), transparent 60%),
    #07080c;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.login-hero::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.045) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(circle at 30% 20%, #000 10%, transparent 72%);
}

.hero-tag {
  position: relative;
  color: #a5b4fc;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.hero-title {
  position: relative;
  font-size: 40px;
  line-height: 1.15;
  letter-spacing: -1.2px;
  margin: 14px 0 12px;
  font-weight: 620;
  color: #e8ebf2;
}

.hero-title em {
  font-style: normal;
  background: linear-gradient(92deg, #818cf8, #22d3ee 70%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.hero-sub {
  position: relative;
  color: #9aa3b5;
  max-width: 430px;
  line-height: 1.75;
  font-size: 13px;
}

.hero-stats {
  position: relative;
  display: flex;
  gap: 34px;
  margin-top: 34px;
  color: #e8ebf2;
}

.hero-stats b {
  display: block;
  font-size: 22px;
  font-weight: 620;
  letter-spacing: -0.4px;
}

.hero-stats span {
  color: #7d869a;
  font-size: 11px;
}

.hero-foot {
  position: relative;
  color: #5f6779;
  font-size: 11px;
}

.login-form-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: var(--surface);
}

.login-form {
  width: 100%;
  max-width: 340px;
}

.login-form h2 {
  margin: 0 0 5px;
  font-size: 19px;
  font-weight: 600;
  letter-spacing: -0.2px;
}

.login-form > p {
  margin: 0 0 22px;
  color: var(--muted);
  font-size: 12px;
}

.form-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 4px 0 16px;
  font-size: 11.5px;
  color: var(--muted);
}

.remember {
  display: flex;
  align-items: center;
  gap: 6px;
}

.error {
  color: var(--err);
  font-size: 11.5px;
  margin: 0 0 10px;
}

.submit {
  width: 100%;
  justify-content: center;
  padding: 10px;
  font-size: 13px;
}

.full {
  width: 100%;
  justify-content: center;
}

.login-sep {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--faint);
  font-size: 10.5px;
  margin: 16px 0;
}

.login-sep::before,
.login-sep::after {
  content: "";
  height: 1px;
  background: var(--line);
  flex: 1;
}

.demo-hint {
  margin-top: 16px;
  border: 1px dashed var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  color: var(--faint);
  font-size: 11px;
  line-height: 1.7;
}

.demo-hint code {
  font-family: var(--mono);
  color: var(--muted);
}

@media (max-width: 1080px) {
  .login {
    grid-template-columns: 1fr;
  }

  .login-hero {
    display: none;
  }
}
</style>
