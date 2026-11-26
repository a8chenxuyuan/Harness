/** Skill 管理 API 封装（W4-01）。

后端接口见 src/harness/platform/api/controllers/skills.py。
所有方法返回解包后的 data（code=0 时），错误抛 ApiError。
*/

import { del, get, patch, post } from "./http";
import type {
  SkillListData,
  SkillPatchBody,
  SkillRegisterBody,
  SkillTriggerTestBody,
  SkillTriggerTestData,
  SkillVersionsData,
} from "./types";

/** GET /skills —— 列出当前全部 Skill。 */
export function listSkills(): Promise<SkillListData> {
  return get<SkillListData>("/skills");
}

/** GET /skills/{name} —— 查单个 Skill 详情；不存在返回 null。 */
export function getSkill(name: string): Promise<{ skill: import("./types").SkillItem | null }> {
  return get<{ skill: import("./types").SkillItem | null }>(`/skills/${encodeURIComponent(name)}`);
}

/** POST /skills —— 注册一个新 Skill（运行时层，同名覆盖）。 */
export function registerSkill(body: SkillRegisterBody): Promise<{
  skill: import("./types").SkillItem;
  replaced: boolean;
}> {
  return post<{ skill: import("./types").SkillItem; replaced: boolean }>("/skills", body);
}

/** DELETE /skills/{name} —— 注销运行时 Skill。低层 Skill 会被后端拒绝（403）。 */
export function deleteSkill(name: string): Promise<{ deleted: boolean }> {
  return del<{ deleted: boolean }>(`/skills/${encodeURIComponent(name)}`);
}

/** POST /skills/trigger-test —— 传一段文本，返回命中的 Skill 列表（仅匹配不激活）。 */
export function triggerSkillTest(body: SkillTriggerTestBody): Promise<SkillTriggerTestData> {
  return post<SkillTriggerTestData>("/skills/trigger-test", body);
}

/** PATCH /skills/{name} —— 启用/禁用一个 Skill（任意来源层，内存态）。 */
export function patchSkill(
  name: string,
  body: SkillPatchBody,
): Promise<{ skill: import("./types").SkillItem }> {
  return patch<{ skill: import("./types").SkillItem }>(
    `/skills/${encodeURIComponent(name)}`,
    body,
  );
}

/** GET /skills/{name}/versions —— 查历史版本（内存态，仅记录被覆盖注册的旧版本）。 */
export function listSkillVersions(name: string): Promise<SkillVersionsData> {
  return get<SkillVersionsData>(`/skills/${encodeURIComponent(name)}/versions`);
}
