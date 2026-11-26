"""``harness`` 命令行入口（W4-API-02）。

基于标准库 argparse（零新依赖），通过 SDK 消费 REST API。
凭据解析见 :mod:`harness.sdk.cli_config`；输出统一为 pretty JSON，
错误输出到 stderr 并以退出码 1 结束。

子命令::

    harness whoami                                   验证凭据
    harness login --api-key hk_xxx [--base-url URL]  验证并保存凭据
    harness skills list|get NAME|register ...|enable NAME|disable NAME
                    |versions NAME|delete NAME|test-trigger TEXT
    harness tools list|market|debug NAME [--args '{}']
    harness memories list [--keyword K]|save CONTENT [--tags a,b]|delete ID
    harness keys create --name N [--expires-days D]|list|revoke ID
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Sequence

from harness.sdk.client import ApiError, HarnessClient
from harness.sdk.cli_config import DEFAULT_BASE_URL, resolve_credential, save_config


# ---------------------------------------------------------------------------
# 参数解析器构建（一个 build_* 一个子命令组）
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """构建顶层解析器（全局参数 --api-key / --base-url）。"""
    parser = argparse.ArgumentParser(
        prog="harness", description="Harness 平台命令行客户端"
    )
    parser.add_argument("--api-key", default=None, help="hk_ 前缀 API Key（默认读环境变量/配置文件）")
    parser.add_argument("--base-url", default=None, help=f"API 根地址（默认 {DEFAULT_BASE_URL}）")
    sub = parser.add_subparsers(dest="resource", required=True)

    sub.add_parser("whoami", help="查询当前调用者身份（验证凭据）")

    login = sub.add_parser("login", help="验证 API Key 并保存到 ~/.harness/config.json")
    login.add_argument("--api-key", required=True, help="hk_ 前缀 API Key")
    login.add_argument("--base-url", default=None, help="API 根地址")

    skills = sub.add_parser("skills", help="Skill 管理")
    skills_sub = skills.add_subparsers(dest="action", required=True)
    skills_sub.add_parser("list", help="列出全部 Skill")
    skill_get = skills_sub.add_parser("get", help="查 Skill 详情")
    skill_get.add_argument("name")
    skill_reg = skills_sub.add_parser("register", help="注册运行时层 Skill")
    skill_reg.add_argument("--name", required=True)
    skill_reg.add_argument("--description", required=True)
    skill_reg.add_argument("--version", default="1.0.0")
    skill_reg.add_argument("--triggers", default="", help="逗号分隔触发词，/regex/ 为正则")
    skill_reg.add_argument("--message", default="", help="命中时追加的 custom_message")
    skill_enable = skills_sub.add_parser("enable", help="启用 Skill")
    skill_enable.add_argument("name")
    skill_disable = skills_sub.add_parser("disable", help="禁用 Skill")
    skill_disable.add_argument("name")
    skill_ver = skills_sub.add_parser("versions", help="查历史版本")
    skill_ver.add_argument("name")
    skill_del = skills_sub.add_parser("delete", help="注销运行时层 Skill")
    skill_del.add_argument("name")
    skill_trig = skills_sub.add_parser("test-trigger", help="触发测试")
    skill_trig.add_argument("text")

    tools = sub.add_parser("tools", help="工具目录 / 市场 / 调试")
    tools_sub = tools.add_subparsers(dest="action", required=True)
    tools_sub.add_parser("list", help="内置工具目录")
    tools_sub.add_parser("market", help="全量工具市场")
    tool_debug = tools_sub.add_parser("debug", help="只读调试执行工具")
    tool_debug.add_argument("name")
    tool_debug.add_argument("--args", default="{}", help="JSON 格式的工具参数")

    memories = sub.add_parser("memories", help="长期记忆管理")
    mem_sub = memories.add_subparsers(dest="action", required=True)
    mem_list = mem_sub.add_parser("list", help="分页查记忆")
    mem_list.add_argument("--keyword", default="")
    mem_list.add_argument("--limit", type=int, default=50)
    mem_save = mem_sub.add_parser("save", help="保存一条记忆")
    mem_save.add_argument("content")
    mem_save.add_argument("--tags", default="", help="逗号分隔标签")
    mem_del = mem_sub.add_parser("delete", help="删除一条记忆")
    mem_del.add_argument("item_id")

    keys = sub.add_parser("keys", help="API Key 管理")
    keys_sub = keys.add_subparsers(dest="action", required=True)
    key_create = keys_sub.add_parser("create", help="签发新 key（明文只打印一次）")
    key_create.add_argument("--name", required=True)
    key_create.add_argument("--expires-days", type=int, default=None)
    keys_sub.add_parser("list", help="列出全部 key（脱敏）")
    key_revoke = keys_sub.add_parser("revoke", help="吊销 key")
    key_revoke.add_argument("key_id")

    return parser


# ---------------------------------------------------------------------------
# 命令执行（每个资源一个 handler，返回待打印的 data）
# ---------------------------------------------------------------------------

async def execute(args: argparse.Namespace) -> Any:
    """执行解析后的命令，返回要打印的 data（login 返回附带提示的 dict）。

    Raises:
        ApiError: 由 SDK 抛出的业务/HTTP 错误，main 统一转退出码。
        ValueError: 缺少凭据时。
        json.JSONDecodeError: --args 不是合法 JSON 时。
    """
    api_key, base_url = resolve_credential(args.api_key, args.base_url)
    if not api_key:
        raise ValueError("缺少凭据：请 harness login，或传 --api-key / 设 HARNESS_API_KEY")

    async with HarnessClient(base_url=base_url, api_key=api_key) as client:
        return await _dispatch(client, args)


async def _dispatch(client: HarnessClient, args: argparse.Namespace) -> Any:
    """按 resource+action 分发到对应 SDK 方法（login 是唯一带副作用的命令）。"""
    if args.resource == "whoami":
        return await client.whoami()
    if args.resource == "login":
        me = await client.whoami()
        path = save_config(args.api_key, args.base_url or base_url_of(args))
        return {"whoami": me, "saved_to": str(path)}
    if args.resource == "skills":
        return await _dispatch_skills(client, args)
    if args.resource == "tools":
        if args.action == "list":
            return await client.tools.list()
        if args.action == "market":
            return await client.tools.market()
        return await client.tools.debug(args.name, json.loads(args.args))
    if args.resource == "memories":
        if args.action == "list":
            return await client.memories.list(keyword=args.keyword, limit=args.limit)
        if args.action == "save":
            tags = [t.strip() for t in args.tags.split(",") if t.strip()]
            return await client.memories.save(args.content, tags=tags)
        return await client.memories.delete(args.item_id)
    # keys
    if args.action == "create":
        return await client.api_keys.create(args.name, expires_in_days=args.expires_days)
    if args.action == "list":
        return await client.api_keys.list()
    return await client.api_keys.revoke(args.key_id)


def base_url_of(args: argparse.Namespace) -> str:
    """login 场景下兜底解析 base_url（参数 > 环境 > 默认值）。"""
    resolved_key, resolved_url = resolve_credential(None, args.base_url)
    return resolved_url


async def _dispatch_skills(client: HarnessClient, args: argparse.Namespace) -> Any:
    """分发 skills 子命令。"""
    if args.action == "list":
        return await client.skills.list()
    if args.action == "get":
        return await client.skills.get(args.name)
    if args.action == "register":
        triggers = [t.strip() for t in args.triggers.split(",") if t.strip()]
        return await client.skills.register(
            args.name,
            args.description,
            version=args.version,
            triggers=triggers,
            custom_message=args.message,
        )
    if args.action == "enable":
        return await client.skills.enable(args.name)
    if args.action == "disable":
        return await client.skills.disable(args.name)
    if args.action == "versions":
        return await client.skills.versions(args.name)
    if args.action == "delete":
        return await client.skills.delete(args.name)
    return await client.skills.trigger_test(args.text)


def main(argv: Sequence[str] | None = None) -> int:
    """同步入口（[project.scripts] 注册点）：解析参数 → 异步执行 → 打印。

    Returns:
        0 成功；1 业务/HTTP 错误；2 参数错误（argparse 默认行为）。
    """
    args = build_parser().parse_args(argv)
    try:
        data = asyncio.run(execute(args))
    except ApiError as exc:
        print(f"error: [{exc.status_code}] code={exc.code} {exc.message}", file=sys.stderr)
        return 1
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


__all__ = ["build_parser", "main"]
