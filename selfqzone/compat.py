"""给搬过来的 qzone 代码用的最小兼容层。"""

from __future__ import annotations

from .post_model import Comment, Post  # noqa: F401


class PluginConfig:
    """qzone 客户端只需要这几样：OneBot 客户端、超时、Cookie 刷新间隔。"""

    def __init__(self, client=None, timeout: int = 30, cookie_ttl: int = 1800) -> None:
        self.client = client
        self.timeout = max(10, int(timeout or 30))
        self.cookie_ttl = max(0, int(cookie_ttl or 0))

    def ensure_client(self) -> None:
        if self.client is None:
            raise RuntimeError("CQHttp 实例不存在")
