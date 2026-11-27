"""企微配置 loader（W4-CHAN-02A）。

读取顺序：优先 env 变量（HARNESS_WECOM__xxx），CHAN-05 时改从 channel_apps 表读取。
"""

from __future__ import annotations

import os
from typing import Any


def load_wecom_config() -> dict[str, str]:
    """从 env 读企微自建应用凭据。

    Returns:
        dict 可能只含部分字段 —— 至少 corp_id + token + encoding_aes_key 才能 receive，
        至少 corp_id + secret + agent_id 才能 send。调用方按 ``ready_for_send`` /
        ``ready_for_receive`` 自行判断。
    """
    prefix = "HARNESS_WECOM__"
    mapping = {
        "corp_id": "CORP_ID",
        "agent_id": "AGENT_ID",
        "secret": "SECRET",
        "token": "TOKEN",
        "encoding_aes_key": "ENCODING_AES_KEY",
    }
    cfg: dict[str, str] = {}
    for key, env_suffix in mapping.items():
        val = os.environ.get(prefix + env_suffix)
        if val:
            cfg[key] = val
    # agent_id 可能是纯数字字符串，adapter 里 int() 转换会处理
    return cfg


def has_any_config() -> bool:
    """是否至少配置了一项企微字段。"""
    return bool(load_wecom_config())


__all__ = ["load_wecom_config", "has_any_config"]
