"""自带的 QQ 空间服务：发 / 删 / 查说说，不依赖 astrbot_plugin_qzone。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from astrbot.api import logger

from .api import QzoneAPI
from .compat import PluginConfig, Post
from .parser import QzoneParser
from .session import QzoneSession


class _BotAdapter:
    """把 qzone_kit 的 `_call_api` 包成 qzone 客户端要的形状。"""

    def __init__(
        self,
        call: Callable[..., Awaitable[Any]],
        cookie: str = "",
    ) -> None:
        self._call = call
        self._cookie = (cookie or "").strip()

    async def get_cookies(self, domain: str = "user.qzone.qq.com") -> dict[str, Any]:
        # 优先问协议端要（最准，能跟着登录状态刷新）
        try:
            payload = await self._call("get_cookies", domain=domain)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[QzoneKit] get_cookies 失败：%s", exc)
            payload = None

        cookies = ""
        if isinstance(payload, dict):
            cookies = str(payload.get("cookies") or "").strip()
        if not cookies and self._cookie:
            logger.info("[QzoneKit] 协议端没给 Cookie，用配置里的 qzone_cookie")
            cookies = self._cookie
        return {"cookies": cookies}

    async def get_login_info(self) -> dict[str, Any]:
        try:
            info = await self._call("get_login_info")
            return info if isinstance(info, dict) else {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("[QzoneKit] get_login_info 失败：%s", exc)
            return {}


class SelfQzoneService:
    """和 QQ空间插件 `service` 同形状的最小实现（只做空间小助手要用的三件事）。"""

    def __init__(
        self,
        call: Callable[..., Awaitable[Any]],
        *,
        timeout: int = 30,
        cookie_ttl: int = 1800,
        cookie: str = "",
    ) -> None:
        self.cfg = PluginConfig(
            _BotAdapter(call, cookie=cookie), timeout=timeout, cookie_ttl=cookie_ttl
        )
        self.session = QzoneSession(self.cfg)
        self.qzone = QzoneAPI(self.session, self.cfg)

    async def close(self) -> None:
        try:
            await self.qzone.close()
        except Exception:  # noqa: BLE001
            pass

    # ── 发说说 ───────────────────────────────────────────────────────
    async def publish_post(
        self,
        *,
        post: Post | None = None,
        text: str | None = None,
        images: list[Any] | None = None,
    ) -> Post:
        if post is None:
            uin = await self.session.get_uin()
            name = await self.session.get_nickname()
            post = Post(
                uin=uin,
                name=name,
                text=text or "",
                images=[str(x) for x in (images or [])],
            )
        resp = await self.qzone.publish(post)
        if not resp.ok:
            raise RuntimeError(f"发布说说失败：{resp.message or resp.data or resp.code}")
        data = resp.data or {}
        post.tid = data.get("tid")
        post.status = "approved"
        post.create_time = data.get("now", post.create_time)
        return post

    # ── 查说说 ───────────────────────────────────────────────────────
    async def query_feeds(
        self,
        *,
        target_id: str | None = None,
        pos: int = 0,
        num: int = 1,
        **_kwargs: Any,
    ) -> list[Post]:
        if target_id:
            resp = await self.qzone.get_feeds(str(target_id), pos=pos, num=num)
            if not resp.ok:
                raise RuntimeError(f"读取说说失败：{resp.message or resp.code}")
            msglist = (resp.data or {}).get("msglist") or []
            return QzoneParser.parse_feeds(msglist) if msglist else []
        resp = await self.qzone.get_recent_feeds(page=1)
        if not resp.ok:
            raise RuntimeError(f"读取说说失败：{resp.message or resp.code}")
        return QzoneParser.parse_recent_feeds(resp.data or {})

    # ── 删说说 ───────────────────────────────────────────────────────
    async def delete_post(self, post: Post) -> None:
        tid = getattr(post, "tid", None)
        if not tid:
            raise ValueError("帖子 tid 为空")
        resp = await self.qzone.delete(str(tid))
        if not resp.ok:
            raise RuntimeError(f"删除说说失败：{resp.message or resp.code}")
