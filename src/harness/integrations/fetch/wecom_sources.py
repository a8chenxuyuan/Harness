"""企微数据源（W4.1-CHAN-06）：wecom_profile + wecom_approval。

profile  ：绑定用户的企微资料（通讯录 user/get），验证框架全链路；
approval ：OA 审批待办（getapprovalinfo + getapprovaldetail），真实"待办"数据。
两个源都复用 WeComAdapter 的 access_token 缓存（corp token）。

真实 API 参考：
    GET  /cgi-bin/user/get?access_token=&userid=
    POST /cgi-bin/oa/getapprovalinfo?access_token=
    POST /cgi-bin/oa/getapprovaldetail?access_token=
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from harness.integrations.fetch.base import ChannelFetcher, FetchedItem

log = logging.getLogger(__name__)


def _ts(dt: datetime) -> int:
    return int(dt.timestamp())


class WeComProfileFetcher(ChannelFetcher):
    """绑定用户的企微资料（通讯录读取）。"""

    platform = "wecom"
    source = "profile"
    item_type = "profile"

    async def fetch(self, binding: Any, cursor: str) -> tuple[list[FetchedItem], str]:
        userid = binding.platform_user_id
        token = await self.adapter._get_access_token()  # noqa: SLF001 复用 token 缓存
        data = await self.platform_request(
            "GET",
            "/cgi-bin/user/get",
            params={"access_token": token, "userid": userid},
        )
        user = data.get("user", data)
        name = user.get("name") or userid
        dept = ",".join(str(d) for d in user.get("department", [])) or "未分配"
        item = FetchedItem(
            external_id=f"profile:{userid}",
            item_type=self.item_type,
            title=name,
            summary=f"企微账号 {userid} · 部门 {dept} · 职位 {user.get('position') or '—'}",
            raw=user,
            occurred_at=datetime.now(timezone.utc),
        )
        return [item], datetime.now(timezone.utc).isoformat()


class WeComApprovalFetcher(ChannelFetcher):
    """企微 OA 审批待办（近 7 天增量拉取，游标记录上次拉取时间）。"""

    platform = "wecom"
    source = "approval"
    item_type = "todo"

    WINDOW_DAYS = 7
    PAGE_SIZE = 100

    async def fetch(self, binding: Any, cursor: str) -> tuple[list[FetchedItem], str]:
        token = await self.adapter._get_access_token()  # noqa: SLF001

        # 游标 = 上次拉取起始时间戳；首拉从 7 天前开始
        if cursor:
            try:
                start = datetime.fromisoformat(cursor)
            except ValueError:
                start = datetime.now(timezone.utc)
        else:
            start = datetime.now(timezone.utc)
        start_ts = _ts(start)
        now = datetime.now(timezone.utc)
        end_ts = _ts(now)

        info = await self.platform_request(
            "POST",
            "/cgi-bin/oa/getapprovalinfo",
            params={"access_token": token},
            json_body={
                "starttime": start_ts,
                "endtime": end_ts,
                "cursor": 0,
                "size": self.PAGE_SIZE,
                "filters": [
                    {"key": "sp_status", "value": ["1", "2", "3", "4", "6", "7", "10"]}
                ],
            },
        )
        sp_nos: list[str] = info.get("sp_no_list", [])
        items: list[FetchedItem] = []
        for sp_no in sp_nos:
            detail = await self.platform_request(
                "POST",
                "/cgi-bin/oa/getapprovaldetail",
                params={"access_token": token},
                json_body={"sp_no": sp_no},
            )
            sp = detail.get("info", {})
            status_map = {1: "审批中", 2: "已通过", 3: "已驳回", 4: "已撤销", 6: "已转审", 7: "已代办", 10: "已删除"}
            status = status_map.get(sp.get("sp_status"), str(sp.get("sp_status")))
            items.append(
                FetchedItem(
                    external_id=sp_no,
                    item_type=self.item_type,
                    title=sp.get("sp_name") or "审批单",
                    summary=f"#{sp_no} · {status} · 申请人 {binding.platform_user_id}",
                    raw=sp,
                    occurred_at=datetime.fromtimestamp(sp.get("apply_time", _ts(now)), tz=timezone.utc),
                )
            )
        return items, now.isoformat()


# 注册表：platform → 数据源实例工厂（runner 按 platform 实例化）
WECOM_FETCHERS: list[type[ChannelFetcher]] = [WeComProfileFetcher, WeComApprovalFetcher]


def get_fetchers(platform: str, adapter: Any) -> list[ChannelFetcher]:
    """返回某平台在给定 adapter 下的全部数据源实例。"""
    registry: dict[str, list[type[ChannelFetcher]]] = {
        "wecom": WECOM_FETCHERS,
    }
    return [cls(adapter) for cls in registry.get(platform, [])]


__all__ = ["WeComApprovalFetcher", "WeComProfileFetcher", "get_fetchers"]
