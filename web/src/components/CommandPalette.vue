/** 命令面板：⌘K / Ctrl+K 打开，支持上下键与回车跳转。 */
<template>
  <Teleport to="body">
    <div v-if="open" class="cmdk" @click.self="$emit('close')">
      <div class="cmdk-box">
        <div class="cmdk-input">
          <span>⌕</span>
          <input
            ref="inputRef"
            v-model="keyword"
            placeholder="搜索页面、会话、运行…"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="select(active)"
            @keydown.esc.prevent="$emit('close')"
          />
        </div>
        <div class="cmdk-list">
          <div
            v-for="(item, index) in filtered"
            :key="item.name"
            class="cmdk-item"
            :class="{ on: index === active }"
            @mouseenter="active = index"
            @click="select(index)"
          >
            <span class="ico">{{ item.icon }}</span>
            {{ item.label }}
            <span class="hint">{{ item.hint }}</span>
          </div>
          <div v-if="filtered.length === 0" class="cmdk-empty">没有匹配项</div>
        </div>
        <div class="cmdk-foot">↑↓ 选择 · ↵ 确认 · Esc 关闭</div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const router = useRouter();
const keyword = ref("");
const active = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);

interface PaletteItem {
  name: string;
  label: string;
  icon: string;
  hint: string;
}

const items: PaletteItem[] = [
  { name: "overview", label: "转到概览", icon: "◫", hint: "G O" },
  { name: "sessions", label: "打开会话列表", icon: "☰", hint: "G S" },
  { name: "agent", label: "新建 Agent 运行", icon: "▶", hint: "G R" },
];

const filtered = computed(() =>
  items.filter((item) => !keyword.value || item.label.includes(keyword.value)),
);

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    keyword.value = "";
    active.value = 0;
    await nextTick();
    inputRef.value?.focus();
  },
);

/** 上下移动选中项。 */
function move(delta: number): void {
  if (filtered.value.length === 0) return;
  active.value = (active.value + delta + filtered.value.length) % filtered.value.length;
}

/** 回车跳转。 */
function select(index: number): void {
  const target = filtered.value[index];
  if (!target) return;
  emit("close");
  void router.push({ name: target.name });
}
</script>

<style scoped>
.cmdk {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 13vh;
  background: rgba(4, 6, 10, 0.62);
  backdrop-filter: blur(3px);
}

.cmdk-box {
  width: 520px;
  max-width: calc(100vw - 40px);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 30px 80px -20px rgba(0, 0, 0, 0.85);
  overflow: hidden;
}

.cmdk-input {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  color: var(--faint);
}

.cmdk-input input {
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  outline: none;
}

.cmdk-list {
  padding: 6px;
}

.cmdk-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 8px;
  color: var(--muted);
  cursor: pointer;
  font-size: 12.5px;
}

.cmdk-item.on,
.cmdk-item:hover {
  background: var(--surface-2);
  color: var(--text);
}

.cmdk-item .hint {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--faint);
}

.cmdk-empty {
  padding: 18px;
  text-align: center;
  color: var(--faint);
  font-size: 12px;
}

.cmdk-foot {
  border-top: 1px solid var(--line);
  padding: 8px 12px;
  color: var(--faint);
  font-size: 10.5px;
}
</style>
