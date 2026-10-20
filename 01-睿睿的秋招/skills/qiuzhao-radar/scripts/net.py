"""零 Python 依赖的 HTTP 客户端。

系统自带的 curl 能正确处理川e就（bigdata.scbdc.edu.cn:8888）的 TLS，
而 Python 3.9 的 urllib 在该站点会握手超时，所以这里统一走 curl。

所有请求都是低频的公开页面读取；不登录、不绕验证码、不提交表单。
"""
from __future__ import annotations

import json
import subprocess
import time
from typing import Dict, Optional

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 "
    "QiuzhaoRadar/0.1"
)


class HttpError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _run(args, timeout: int) -> str:
    cmd = [
        "curl", "-sS", "-L", "--compressed",
        "--max-time", str(timeout),
        "-A", UA,
    ] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    except FileNotFoundError as exc:
        raise HttpError("找不到 curl；本 skill 需要系统 curl") from exc
    except subprocess.TimeoutExpired as exc:
        raise HttpError("curl 超时") from exc
    if p.returncode != 0:
        raise HttpError(f"curl 失败（{p.returncode}）：{p.stderr.strip()[:300]}")
    return p.stdout


def get(url: str, headers: Optional[Dict[str, str]] = None,
        insecure: bool = False, timeout: int = 30) -> str:
    args = []
    if insecure:
        args.append("-k")
    for k, v in (headers or {}).items():
        args += ["-H", f"{k}: {v}"]
    args += ["-w", "\n__HTTP_STATUS__:%{http_code}", url]
    out = _run(args, timeout)
    try:
        body, status_s = out.rsplit("\n__HTTP_STATUS__:", 1)
        status = int(status_s.strip())
    except (ValueError, TypeError):
        raise HttpError("curl 返回格式异常", body=out[:300])
    if status >= 400:
        raise HttpError(f"HTTP {status}: {url}", status=status, body=body[:500])
    return body


def post_form(url: str, data: Dict[str, str],
              headers: Optional[Dict[str, str]] = None,
              insecure: bool = False, timeout: int = 30) -> str:
    args = ["-X", "POST"]
    if insecure:
        args.append("-k")
    hdrs = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    hdrs.update(headers or {})
    for k, v in hdrs.items():
        args += ["-H", f"{k}: {v}"]
    for k, v in data.items():
        args += ["--data-urlencode", f"{k}={v}"]
    args += ["-w", "\n__HTTP_STATUS__:%{http_code}", url]
    out = _run(args, timeout)
    try:
        body, status_s = out.rsplit("\n__HTTP_STATUS__:", 1)
        status = int(status_s.strip())
    except (ValueError, TypeError):
        raise HttpError("curl 返回格式异常", body=out[:300])
    if status >= 400:
        raise HttpError(f"HTTP {status}: {url}", status=status, body=body[:500])
    return body


def post_json(url: str, payload, headers: Optional[Dict[str, str]] = None,
              insecure: bool = False, timeout: int = 30) -> str:
    args = ["-X", "POST"]
    if insecure:
        args.append("-k")
    hdrs = {"Content-Type": "application/json; charset=UTF-8"}
    hdrs.update(headers or {})
    for k, v in hdrs.items():
        args += ["-H", f"{k}: {v}"]
    args += ["--data-binary", json.dumps(payload, ensure_ascii=False)]
    args += ["-w", "\n__HTTP_STATUS__:%{http_code}", url]
    out = _run(args, timeout)
    try:
        body, status_s = out.rsplit("\n__HTTP_STATUS__:", 1)
        status = int(status_s.strip())
    except (ValueError, TypeError):
        raise HttpError("curl 返回格式异常", body=out[:300])
    if status >= 400:
        raise HttpError(f"HTTP {status}: {url}", status=status, body=body[:500])
    return body


def get_json(url: str, **kwargs):
    return json.loads(get(url, **kwargs))


class RateLimiter:
    """同一域名两次请求之间至少间隔 seconds 秒。"""

    def __init__(self, seconds: float = 0.6):
        self.seconds = seconds
        self._last = 0.0

    def wait(self):
        delta = time.time() - self._last
        if delta < self.seconds:
            time.sleep(self.seconds - delta)
        self._last = time.time()
