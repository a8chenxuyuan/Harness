/** 根组件：路由出口 + 全局 toast。 */
<template>
  <RouterView />
  <ToastHost />
</template>

<script setup lang="ts">
import ToastHost from "@/components/ToastHost.vue";
</script>
