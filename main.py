"""Harness 生产启动入口。

用法：
    python main.py                  # 直接启动
    uvicorn main:app --reload       # 开发热重载

配置：HARNESS_DATABASE_URL / HARNESS_JWT_SECRET 等环境变量，
或 .env 文件（见 harness.common.config.settings.Settings）。
"""

from __future__ import annotations

import uvicorn

from harness.app import create_app

# 供 uvicorn main:app 使用
app = create_app()


def main() -> None:
    """按 Settings 启动 HTTP 服务。"""
    from harness.common.config.settings import Settings

    settings = Settings()
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
