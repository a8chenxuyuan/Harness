/** 会话详情页：元数据 + 消息占位（后端暂无 messages 接口）。 */
<template>
  <div>
    <PageHeader :title="session?.title ?? '会话详情'" :subtitle="subtitle">
      <template #actions>
        <button class="btn ghost" @click="router.push('/sessions')">返回列表</button>
        <button class="btn primary" @click="router.push('/agent')">继续对话</button>
        <button class="btn danger" @click="remove">删除</button>
      </template>
    </PageHeader>

    <div v-if="loading" class="panel loading">加载中…</div>
    <div v-else-if="error" class="panel loading">{{ error }}</div>

    <div v-else class="split">
      <div class="panel">
        <div class="panel-head"><h3>消息</h3><span class="muted">只读</span></div>
        <div class="empty">
          <div class="empty-icon">☰</div>
          <div class="empty-title">消息内容暂未开放</div>
          <p class="empty-desc">
            后端当前只返回会话元数据（无 messages 接口）。本页先展示元数据与占位空态，待接口补齐后接入。
          </p>
        </div>
      </div>

      <div class="side-panel">
        <div class="panel mini">
          <h4>会话信息</h4>
          <p class="mono">GET /api/v1/sessions/{{ session?.session_id }}</p>
          <ul class="timeline">
            <li class="done"><b>tenant_id</b><span>{{ session?.tenant_id ?? "—" }}</span></li>
            <li class="done"><b>status</b><span>{{ session?.status }}</span></li>
            <li class="done"><b>message_count</b><span>{{ session?.message_count }}</span></li>
            <li class="done"><b>updated_at</b><span>{{ session?.updated_at }}</span></li>
          </ul>
        </div>
        <div class="panel mini">
          <h4>关联运行</h4>
          <p>跑一次 Agent 看看时间线与输出</p>
          <button class="btn ghost" style="margin-top: 10px" @click="router.push('/agent')">查看运行详情</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { getSession, removeSession } from "@/api/sessions";
import type { SessionDetail } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const route = useRoute();
const router = useRouter();
const loading = ref(true);
const error = ref("");
const session = ref<SessionDetail | null>(null);

const subtitle = computed(() =>
  session.value ? `${session.value.session_id} · ${session.value.status} · ${session.value.message_count} 条消息` : "",
);

async function reload(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    session.value = await getSession(String(route.params.id));
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

/** 删除会话：二次确认后回列表。 */
async function remove(): Promise<void> {
  if (!window.confirm("确认删除该会话？")) return;
  try {
    await removeSession(String(route.params.id));
    pushToast("已删除（mock 环境不会真正删除）");
    await router.push("/sessions");
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "删除失败");
  }
}

onMounted(reload);
</script>

<style scoped>
.loading {
  padding: 40px;
  text-align: center;
  color: var(--faint);
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
