/** Skill 管理页：卡片式列表 + 注册弹窗 + 触发测试 + 卸载。 */
<template>
  <div>
    <PageHeader title="Skill 管理" subtitle="Skill 是 Agent 的人格/专家视角包，命中触发词后自动追加 custom_message">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="reload">刷新</button>
        <button class="btn primary" @click="showRegister = true">注册 Skill</button>
      </template>
    </PageHeader>

    <div class="panel">
      <!-- 触发测试面板 -->
      <div class="trigger-panel">
        <input
          v-model.trim="triggerText"
          placeholder="输入一段文本，测试哪些 Skill 会命中…"
          class="input"
          @keyup.enter="runTriggerTest"
        />
        <button class="btn primary" :disabled="!triggerText || triggerTesting" @click="runTriggerTest">
          {{ triggerTesting ? "测试中…" : "测试触发" }}
        </button>
        <div v-if="triggerMatches.length" class="trigger-result">
          命中 <b>{{ triggerMatches.length }}</b> 个：
          <span v-for="m in triggerMatches" :key="m.name" class="pill ok">
            {{ m.name }} <span class="muted">via {{ m.matched_trigger }}</span>
          </span>
        </div>
      </div>

      <!-- 卡片列表 -->
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="items.length === 0" class="empty">暂无 Skill。内置 Skill 通常存放在项目目录 .harness/skills/ 下。</div>
      <div v-else class="skill-grid">
        <div v-for="skill in items" :key="skill.name" class="skill-card" :class="{ disabled: !skill.enabled }">
          <div class="card-head">
            <span class="pill" :class="sourceClass(skill.source)">{{ skill.source }}</span>
            <span class="name">{{ skill.name }}</span>
            <span class="ver muted">v{{ skill.version }}</span>
            <label class="switch" :title="skill.enabled ? '已启用，点击禁用' : '已禁用，点击启用'">
              <input type="checkbox" :checked="skill.enabled" @change="handleToggle(skill)" />
              <span class="slider"></span>
            </label>
          </div>
          <div v-if="skill.description" class="desc">{{ skill.description }}</div>
          <div v-if="skill.triggers.length" class="chips">
            <span class="chip" v-for="t in skill.triggers" :key="t" :title="t">{{ t }}</span>
          </div>
          <div v-if="skill.tools.length" class="chips">
            <span class="chip tool" v-for="t in skill.tools" :key="t">{{ t }}</span>
          </div>
          <div class="custom-msg" v-if="skill.custom_message" :title="skill.custom_message">
            {{ skill.custom_message.length > 100 ? skill.custom_message.slice(0, 100) + "…" : skill.custom_message }}
          </div>
          <div class="card-foot">
            <button class="btn ghost sm" @click="openVersions(skill)">版本</button>
            <button class="btn ghost sm" :disabled="skill.source !== 'runtime'" @click="handleDelete(skill)">
              {{ skill.source !== "runtime" ? "低层不可删" : "卸载" }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 注册弹窗 -->
    <div v-if="showRegister" class="modal-backdrop" @click.self="showRegister = false">
      <div class="modal">
        <h3>注册新 Skill（运行时层）</h3>
        <p class="muted">运行时层优先级最高，会覆盖 bundled/project/user 的同名版本。进程重启后丢失，持久化请写到 .harness/skills/ 目录。</p>
        <label>
          <span>名称 *</span>
          <input v-model.trim="reg.name" placeholder="如 code-reviewer" />
        </label>
        <label>
          <span>描述</span>
          <input v-model.trim="reg.description" placeholder="简短说明" />
        </label>
        <label>
          <span>版本</span>
          <input v-model.trim="reg.version" placeholder="1.0.0" />
        </label>
        <label>
          <span>触发词（回车分隔，支持 /regex/）</span>
          <textarea v-model="triggersText" rows="3" placeholder="code review&#10;写代码&#10;/bug.*fix/"></textarea>
        </label>
        <label>
          <span>关联工具名（回车分隔）</span>
          <textarea v-model="toolsText" rows="2" placeholder="bash&#10;write_file"></textarea>
        </label>
        <label>
          <span>Custom Message（命中后追加的专家视角）</span>
          <textarea v-model="reg.custom_message" rows="4" placeholder="你是一名资深代码审查专家…"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showRegister = false">取消</button>
          <button class="btn primary" :disabled="!reg.name || registering" @click="handleRegister">
            {{ registering ? "注册中…" : "注册" }}
          </button>
        </div>
      </div>
    </div>
    <!-- 版本历史弹窗 -->
    <div v-if="versionsOf" class="modal-backdrop" @click.self="versionsOf = null">
      <div class="modal">
        <h3>历史版本：{{ versionsOf }}</h3>
        <p class="muted">仅记录 API 覆盖注册时被替换的旧版本（内存态，进程重启后清空）。</p>
        <div v-if="versionsLoading" class="empty">加载中…</div>
        <div v-else-if="versions.length === 0" class="empty">暂无历史版本。同名覆盖注册后才会产生记录。</div>
        <table v-else class="ver-table">
          <thead>
            <tr><th>版本</th><th>来源</th><th>说明</th><th>被覆盖时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="(v, i) in versions" :key="i">
              <td>v{{ v.version }}</td>
              <td><span class="pill" :class="sourceClass(v.source)">{{ v.source }}</span></td>
              <td class="muted">{{ v.description || "—" }}</td>
              <td class="muted">{{ v.replaced_at }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn ghost" @click="versionsOf = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";

import { deleteSkill, listSkillVersions, listSkills, patchSkill, registerSkill, triggerSkillTest } from "@/api/skills";
import type { SkillItem, SkillRegisterBody, SkillTriggerMatch, SkillVersionItem } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const items = ref<SkillItem[]>([]);
const loading = ref(false);
const showRegister = ref(false);
const registering = ref(false);
const triggerText = ref("");
const triggerTesting = ref(false);
const triggerMatches = ref<SkillTriggerMatch[]>([]);
const versionsOf = ref<string | null>(null);
const versions = ref<SkillVersionItem[]>([]);
const versionsLoading = ref(false);

const reg = reactive<SkillRegisterBody>({
  name: "",
  description: "",
  version: "1.0.0",
  custom_message: "",
});
const triggersText = ref("");
const toolsText = ref("");

const sourceClass = (s: string): string => {
  if (s === "runtime") return "ok";
  if (s === "user") return "info";
  if (s === "project") return "info";
  return "warn";
};

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const data = await listSkills();
    items.value = data.items;
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "加载失败");
  } finally {
    loading.value = false;
  }
}

async function runTriggerTest(): Promise<void> {
  if (!triggerText.value.trim()) return;
  triggerTesting.value = true;
  try {
    const data = await triggerSkillTest({ text: triggerText.value.trim() });
    triggerMatches.value = data.matched;
    pushToast(`命中 ${data.total_matches} 个 Skill`);
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "测试失败");
  } finally {
    triggerTesting.value = false;
  }
}

async function handleRegister(): Promise<void> {
  if (!reg.name.trim()) return;
  registering.value = true;
  try {
    await registerSkill({
      ...reg,
      triggers: splitLines(triggersText.value),
      tools: splitLines(toolsText.value),
    });
    pushToast("Skill 注册成功");
    showRegister.value = false;
    resetRegister();
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "注册失败");
  } finally {
    registering.value = false;
  }
}

async function handleDelete(skill: SkillItem): Promise<void> {
  if (!confirm(`确认卸载 Skill "${skill.name}"？`)) return;
  try {
    await deleteSkill(skill.name);
    pushToast("已卸载");
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "卸载失败");
  }
}

/** 启用/禁用一个 Skill（任意来源层均可，内存态）。 */
async function handleToggle(skill: SkillItem): Promise<void> {
  const target = !skill.enabled;
  try {
    await patchSkill(skill.name, { enabled: target });
    pushToast(target ? `已启用 ${skill.name}` : `已禁用 ${skill.name}`);
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "操作失败");
    await reload();
  }
}

/** 打开版本历史弹窗并拉取数据。 */
async function openVersions(skill: SkillItem): Promise<void> {
  versionsOf.value = skill.name;
  versions.value = [];
  versionsLoading.value = true;
  try {
    const data = await listSkillVersions(skill.name);
    versions.value = data.items;
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "加载版本历史失败");
  } finally {
    versionsLoading.value = false;
  }
}

function resetRegister(): void {
  reg.name = "";
  reg.description = "";
  reg.version = "1.0.0";
  reg.custom_message = "";
  triggersText.value = "";
  toolsText.value = "";
}

function splitLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

void reload();
</script>

<style scoped>
.trigger-panel {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 12px 16px;
  background: var(--panel-alt, #f8f9fb);
  border-radius: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.trigger-panel .input {
  flex: 1;
  min-width: 240px;
  padding: 8px 12px;
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 6px;
  background: var(--bg, #fff);
}
.trigger-result {
  flex-basis: 100%;
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.trigger-result .pill {
  margin: 0;
}
.trigger-result .muted {
  opacity: 0.6;
  font-size: 12px;
}
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}
.skill-card {
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--bg, #fff);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-head .name {
  font-weight: 600;
  font-size: 15px;
}
.card-head .ver {
  font-size: 12px;
  margin-left: auto;
}
/* 启用/禁用开关 */
.switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 34px;
  height: 18px;
  flex-shrink: 0;
  cursor: pointer;
}
.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}
.switch .slider {
  position: absolute;
  inset: 0;
  background: var(--border, #ccc);
  border-radius: 9px;
  transition: background 0.2s;
}
.switch .slider::before {
  content: "";
  position: absolute;
  width: 14px;
  height: 14px;
  left: 2px;
  top: 2px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s;
}
.switch input:checked + .slider {
  background: var(--accent, #3b82f6);
}
.switch input:checked + .slider::before {
  transform: translateX(16px);
}
/* 禁用态卡片整体淡化 */
.skill-card.disabled {
  opacity: 0.55;
}
/* 版本历史表格 */
.ver-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.ver-table th,
.ver-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border, #e1e3e8);
}
.ver-table th {
  color: var(--fg-dim, #666);
  font-weight: 500;
}
.desc {
  font-size: 13px;
  color: var(--fg-dim, #666);
}
.chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.chip {
  background: var(--panel-alt, #f0f2f5);
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 12px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--fg, #333);
}
.chip.tool {
  background: var(--accent-bg, #eef6ff);
  border-color: var(--accent, #3b82f6);
  color: var(--accent, #3b82f6);
}
.custom-msg {
  font-family: monospace;
  font-size: 12px;
  color: var(--fg-dim, #666);
  background: var(--panel-alt, #f8f9fb);
  padding: 6px 8px;
  border-radius: 4px;
  overflow: hidden;
}
.card-foot {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
}
.btn.sm {
  padding: 4px 10px;
  font-size: 12px;
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--bg, #fff);
  border-radius: 10px;
  padding: 24px;
  width: 480px;
  max-height: 85vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.modal h3 {
  margin: 0;
}
.modal label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}
.modal input,
.modal textarea {
  padding: 6px 10px;
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  resize: vertical;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.muted {
  opacity: 0.6;
  font-size: 12px;
}
</style>
