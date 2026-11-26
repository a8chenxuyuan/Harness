/** 全局 toast 宿主，挂在 App 根部。 */
<template>
  <Teleport to="body">
    <div class="toast-stack">
      <TransitionGroup name="toast">
        <div v-for="item in toastState.items" :key="item.id" class="toast">
          {{ item.text }}
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { toastState } from "@/composables/toast";
</script>

<style scoped>
.toast-stack {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 90;
  display: grid;
  gap: 8px;
}

.toast {
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 3px solid var(--ok);
  border-radius: 10px;
  padding: 11px 14px;
  font-size: 12px;
  color: var(--text);
  box-shadow: var(--shadow);
}

.toast-enter-active,
.toast-leave-active {
  transition: 0.22s;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
