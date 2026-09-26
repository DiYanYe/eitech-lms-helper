# -*- coding: utf-8 -*-
"""httpx 会话封装：Cookie 注入、拟人限速、风控/失效识别。"""
import random
import time

import httpx

from app import config


class RiskControlError(Exception):
    """命中平台风控（412/403/429）。"""


class SessionExpiredError(Exception):
    """登录态失效（响应跳转登录页）。"""


_EXPIRE_MARKERS = ("passport2.chaoxing.com", "统一身份认证")


class ChaoxingSession:
    """统一请求入口：所有只读接口请求都经过限速与风控检查。

    默认不跟随重定向（downloadData 等需手动拿 Location）；需要跟随的调用
    传 follow_redirects=True。
    """

    def __init__(self, cookies: dict):
        self.client = httpx.Client(
            cookies=cookies,
            headers={
                "User-Agent": config.UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=config.HTTP_TIMEOUT,
            follow_redirects=False,
        )

    @staticmethod
    def _throttle():
        time.sleep(random.uniform(*config.REQUEST_DELAY))

    @staticmethod
    def _check_status(resp: httpx.Response):
        if resp.status_code in (412, 429):
            raise RiskControlError(f"风控响应 HTTP {resp.status_code}：{resp.url}")
        if resp.status_code == 403:
            raise RiskControlError(f"403：{resp.url}")

    @staticmethod
    def _check_expire(resp: httpx.Response):
        ctype = resp.headers.get("content-type", "")
        if "text/html" in ctype:
            head = resp.text[:20000]
            for marker in _EXPIRE_MARKERS:
                if marker in head:
                    raise SessionExpiredError(f"登录态失效（响应含“{marker}”）：{resp.url}")

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        """统一请求入口：限速 + 传输层错误退避重试（最多 3 次尝试）+ 风控检查。"""
        last_exc = None
        for attempt in range(3):
            self._throttle()
            try:
                resp = self.client.request(method, url, **kw)
                self._check_status(resp)
                return resp
            except httpx.TransportError as e:  # 瞬时网络错误：退避后重试
                last_exc = e
                time.sleep(2 * (attempt + 1))
        raise last_exc

    def get(self, url: str, **kw) -> httpx.Response:
        resp = self.request("GET", url, **kw)
        if resp.status_code == 200:
            self._check_expire(resp)
        return resp

    def post(self, url: str, **kw) -> httpx.Response:
        resp = self.request("POST", url, **kw)
        if resp.status_code == 200:
            self._check_expire(resp)
        return resp

    def close(self):
        self.client.close()
