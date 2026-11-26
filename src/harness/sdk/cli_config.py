"""CLI 配置解析：凭据优先级 + 配置文件读写（W4-API-02）。

优先级（高 → 低）：命令行参数 > 环境变量 > ~/.harness/config.json。
配置文件路径可用环境变量 ``HARNESS_CONFIG_FILE`` 覆盖（测试用）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ENV_API_KEY = "HARNESS_API_KEY"
ENV_BASE_URL = "HARNESS_BASE_URL"
ENV_CONFIG_FILE = "HARNESS_CONFIG_FILE"

DEFAULT_BASE_URL = "http://localhost:8010/api/v1"


def config_file_path() -> Path:
    """返回配置文件路径（``~/.harness/config.json``，可被环境变量覆盖）。"""
    override = os.environ.get(ENV_CONFIG_FILE, "")
    if override:
        return Path(override)
    return Path.home() / ".harness" / "config.json"


def load_config() -> dict:
    """读取配置文件；不存在或内容非法时返回空 dict（不报错，CLI 可首次 login）。"""
    path = config_file_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(api_key: str, base_url: str) -> Path:
    """保存凭据到配置文件（login 成功后调用）。

    Returns:
        实际写入的配置文件路径（打印给用户）。
    """
    path = config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"api_key": api_key, "base_url": base_url}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def resolve_credential(
    arg_api_key: str | None,
    arg_base_url: str | None,
) -> tuple[str, str]:
    """按优先级解析 (api_key, base_url)。

    Raises:
        SystemExit: 由 argparse 层在调用前检查；本函数只做解析，
            缺 key 时返回空串，由调用方提示先 login 或传 --api-key。
    """
    api_key = arg_api_key or os.environ.get(ENV_API_KEY, "") or str(load_config().get("api_key", ""))
    base_url = (
        arg_base_url
        or os.environ.get(ENV_BASE_URL, "")
        or str(load_config().get("base_url", ""))
        or DEFAULT_BASE_URL
    )
    return api_key, base_url


__all__ = [
    "DEFAULT_BASE_URL",
    "config_file_path",
    "load_config",
    "resolve_credential",
    "save_config",
]
