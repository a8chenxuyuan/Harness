"""企微配置 loader（W4-CHAN-02A）。

读取顺序：os.environ（HARNESS_WECOM__xxx）优先，缺失字段回退
Settings().channels.wecom（由 pydantic-settings 从 .env 加载）。
CHAN-05 时再增加 channel_apps 表来源。
"""

from __future__ import annotations

import os

_ENV_KEYS = {
    "corp_id": "HARNESS_WECOM__CORP_ID",
    "agent_id": "HARNESS_WECOM__AGENT_ID",
    "secret": "HARNESS_WECOM__SECRET",
    "token": "HARNESS_WECOM__TOKEN",
    "encoding_aes_key": "HARNESS_WECOM__ENCODING_AES_KEY",
}


def load_wecom_config() -> dict[str, str]:
    """读取企微自建应用凭据（env 优先，.env 回退）。

    Returns:
        dict 可能只含部分字段 —— receive 需要 corp_id + token +
        encoding_aes_key；send 需要 corp_id + secret + agent_id。
        调用方按 ``ready_for_send`` / ``ready_for_receive`` 判断。
    """
    cfg = {k: v for k, env in _ENV_KEYS.items() if (v := os.environ.get(env))}
    if len(cfg) == len(_ENV_KEYS):
        return cfg  # env 已齐全，无需回退

    try:
        from harness.common.config.settings import Settings

        wecom = Settings().wecom
    except Exception:  # noqa: BLE001 — Settings 构造失败时只走 env
        return cfg

    for key in _ENV_KEYS:
        if not cfg.get(key):
            value = getattr(wecom, key, "")
            if value:
                cfg[key] = value
    return cfg


def has_any_config() -> bool:
    """是否至少配置了一项企微字段。"""
    return bool(load_wecom_config())


__all__ = ["load_wecom_config", "has_any_config"]
