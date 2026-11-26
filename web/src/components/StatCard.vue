/** KPI 卡片：指标值 + 环比 + 迷你折线。 */
<template>
  <div class="kpi">
    <div class="kpi-label">
      {{ label }}
      <span class="mono">{{ hint }}</span>
    </div>
    <div class="kpi-value">
      {{ value }}
      <small v-if="unit">{{ unit }}</small>
    </div>
    <div class="delta" :class="{ down: down }">{{ delta }}</div>
    <svg class="spark" viewBox="0 0 160 30" preserveAspectRatio="none">
      <polyline :points="points" fill="none" :stroke="color" stroke-width="1.6" />
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    unit?: string;
    hint?: string;
    delta: string;
    down?: boolean;
    tone?: "accent" | "ok" | "cyan" | "warn";
    points?: string;
  }>(),
  {
    unit: "",
    hint: "",
    down: false,
    tone: "accent",
    points: "0,24 20,20 40,22 60,14 80,16 100,9 120,11 140,5 160,7",
  },
);

const colors: Record<string, string> = {
  accent: "#6366f1",
  ok: "#34d399",
  cyan: "#22d3ee",
  warn: "#fbbf24",
};

const color = computed(() => colors[props.tone] ?? colors.accent);
</script>

<style scoped>
.kpi {
  background: linear-gradient(180deg, var(--surface-2), var(--surface));
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 14px 10px;
  box-shadow: var(--shadow);
  position: relative;
  overflow: hidden;
}

.kpi::after {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(99, 102, 241, 0.6), transparent);
}

.kpi-label {
  color: var(--muted);
  font-size: 11px;
  display: flex;
  justify-content: space-between;
}

.kpi-value {
  font-size: 26px;
  font-weight: 620;
  letter-spacing: -0.6px;
  margin: 6px 0 2px;
  font-variant-numeric: tabular-nums;
}

.kpi-value small {
  font-size: 12px;
  color: var(--faint);
  font-weight: 400;
  margin-left: 4px;
}

.delta {
  font-size: 11px;
  color: var(--ok);
  font-family: var(--mono);
}

.delta.down {
  color: var(--err);
}

.spark {
  margin-top: 8px;
  height: 30px;
  width: 100%;
  display: block;
}
</style>
