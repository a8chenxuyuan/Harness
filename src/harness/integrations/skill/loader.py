"""SkillLoader：从磁盘加载 SKILL.md 定义。

SKILL.md 采用 frontmatter（YAML）+ 正文的格式，正文就是 custom_message。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from .model import Skill

log = logging.getLogger(__name__)

# frontmatter 分隔符
_FM_DELIM = "---"


class SkillLoadError(Exception):
    """加载单个 SKILL.md 失败时抛出。"""


class SkillLoader:
    """从文件系统加载 Skill 定义。

    典型 SKILL.md 结构：

        ---
        name: code-reviewer
        version: 1.2.0
        triggers:
          - "请评审"
          - /review$/
        tools:
          - read_file
          - bash
        ---

        你是一个代码评审专家，擅长发现性能和安全问题...

    """

    # --- 公共入口 --------------------------------------------------------------

    async def load_dir(self, path: str | os.PathLike[str]) -> list[Skill]:
        """递归扫描目录下所有 SKILL.md，解析并返回 Skill 列表。

        Args:
            path: 技能根目录。不存在时返回空列表（不抛异常，便于上层容错）。

        Returns:
            解析成功的 Skill 实例列表。同名 skill 的覆盖由 repository 层负责。
        """
        root = Path(path)
        if not root.exists():
            log.debug("SkillLoader: 目录不存在，跳过 %s", root)
            return []
        if not root.is_dir():
            log.warning("SkillLoader: %s 不是目录，跳过", root)
            return []

        skills: list[Skill] = []
        for skill_md in root.rglob("SKILL.md"):
            try:
                text = skill_md.read_text(encoding="utf-8")
                skill = self.parse_skill_md(text)
                skills.append(skill)
            except SkillLoadError as exc:
                log.warning("SkillLoader: 解析失败 %s — %s", skill_md, exc)
            except OSError as exc:
                log.warning("SkillLoader: 读取失败 %s — %s", skill_md, exc)
        return skills

    # --- 解析 ------------------------------------------------------------------

    def parse_skill_md(self, content: str) -> Skill:
        """解析一段 SKILL.md 文本为 Skill。

        Args:
            content: SKILL.md 完整文本。

        Returns:
            Skill 实例。

        Raises:
            SkillLoadError: frontmatter 缺失、name 缺失或 yaml 解析失败且
                fallback 也无法提取 name 时抛出。
        """
        fm_fields, body = self._split_frontmatter(content)

        # frontmatter 必须有 name
        name = fm_fields.pop("name", None)
        if not name or not isinstance(name, str):
            raise SkillLoadError("frontmatter 缺少 name 字段")

        version = str(fm_fields.pop("version", "1.0.0"))
        description = str(fm_fields.pop("description", ""))
        triggers = self._as_string_list(fm_fields.pop("triggers", []))
        tools = self._as_string_list(fm_fields.pop("tools", []))

        # 剩余 frontmatter 字段全部进 metadata
        metadata: dict[str, Any] = {k: v for k, v in fm_fields.items()}

        return Skill(
            name=name.strip(),
            description=description.strip(),
            version=version.strip(),
            triggers=triggers,
            tools=tools,
            custom_message=body.strip(),
            metadata=metadata,
        )

    # --- 内部工具 --------------------------------------------------------------

    def _split_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """把内容切分为 (frontmatter_dict, body_text)。"""
        stripped = content.lstrip("\ufeff").lstrip()  # 去 BOM 和前导空白
        lines = stripped.splitlines()

        if not lines or lines[0].strip() != _FM_DELIM:
            raise SkillLoadError("SKILL.md 必须以 '---' 开头")

        # 找到闭合的 ---
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == _FM_DELIM:
                end_idx = i
                break
        if end_idx is None:
            raise SkillLoadError("frontmatter 未闭合")

        fm_text = "\n".join(lines[1:end_idx])
        body = "\n".join(lines[end_idx + 1 :])

        fm_dict = self._parse_yaml(fm_text)
        return fm_dict, body

    @staticmethod
    def _parse_yaml(text: str) -> dict[str, Any]:
        """YAML 解析 + 简单 fallback，避免因 PyYAML 缺失导致整个系统挂掉。"""
        text = text.strip()
        if not text:
            return {}

        # 主路径：用 yaml
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
            if data is None:
                return {}
            if not isinstance(data, dict):
                raise SkillLoadError(f"frontmatter 必须是 mapping，得到 {type(data).__name__}")
            return data
        except ImportError:
            log.debug("PyYAML 未安装，使用 fallback 行解析")
        except Exception as exc:  # noqa: BLE001
            log.debug("YAML 解析失败，使用 fallback: %s", exc)

        # Fallback：简单行解析（只支持顶层 key: value 和 - list 项）
        return SkillLoader._fallback_parse(text)

    @staticmethod
    def _fallback_parse(text: str) -> dict[str, Any]:
        """极简 frontmatter fallback。只处理形如 `key: value` 和缩进 `- item`。"""
        result: dict[str, Any] = {}
        current_key: str | None = None

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue

            # 列表项（缩进开头 - ）
            list_match = re.match(r"^\s*-\s*(.+)$", raw_line)
            if list_match and current_key:
                item = list_match.group(1).strip().strip('"').strip("'")
                existing = result.setdefault(current_key, [])
                if isinstance(existing, list):
                    existing.append(item)
                continue

            # 普通 key: value
            kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
            if kv:
                current_key = kv.group(1)
                value = kv.group(2).strip()
                if value == "":
                    result[current_key] = []  # 空值视为列表占位，下面接 - item
                else:
                    result[current_key] = value.strip('"').strip("'")
        return result

    @staticmethod
    def _as_string_list(value: Any) -> list[str]:
        """把任意值归一化成字符串列表。"""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            return [value]
        return [str(value)]
