"""直播流抓帧与流地址探测。

合规说明：本模块只读取使用者自行配置、且已获授权观看的流地址，
不提供、不破解、不绕过任何加密或付费内容。聚合站点的流地址通常由 JS
动态生成，probe_m3u8() 仅做「把页面里明文出现的 m3u8 提取出来」这一件事，
等价于浏览器开发者工具 Network 面板里能看到的内容；失败时请手动复制地址。
"""
from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import cv2
import numpy as np
import requests

log = logging.getLogger(__name__)

M3U8_RE = re.compile(r"https?://[^\s\"'<>\\)]+\.m3u8[^\s\"'<>\\)]*", re.I)
REL_M3U8_RE = re.compile(r"[\"']([^\"']+\.m3u8[^\"']*)[\"']", re.I)
JS_RE = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)
ESCAPED_RE = re.compile(r"%3A|%2F|%3F|%3D|%26", re.I)


@dataclass
class Frame:
    image: Any
    ts: float
    index: int


def probe_m3u8(page_url: str, timeout: int = 15,
               user_agent: str = "Mozilla/5.0") -> list[str]:
    """从直播间页面 HTML 及其引用的 JS 中提取明文 m3u8 地址。"""
    headers = {"User-Agent": user_agent, "Referer": page_url}
    found: list[str] = []
    try:
        html = requests.get(page_url, headers=headers, timeout=timeout).text
    except Exception as exc:  # noqa: BLE001
        log.warning("页面请求失败: %s", exc)
        return found

    def _collect(text: str, base: str) -> None:
        for u in M3U8_RE.findall(text):
            found.append(u.replace("\\/", "/"))
        for u in REL_M3U8_RE.findall(text):
            u = u.replace("\\/", "/")
            if u.startswith("//"):
                u = "https:" + u
            elif u.startswith("/"):
                u = urljoin(base, u)
            if u.lower().startswith("http"):
                found.append(u)
        # 常见 base64 包装的流地址
        for b64 in re.findall(r"[A-Za-z0-9+/]{40,}={0,2}", text):
            if ".m3u8" not in b64:
                try:
                    dec = base64.b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-8", "ignore")
                except Exception:  # noqa: BLE001
                    continue
                found.extend(M3U8_RE.findall(dec))
            # 简单 %xx 还原
        found.extend(M3U8_RE.findall(requests.utils.unquote(text)))

    _collect(html, page_url)
    for src in JS_RE.findall(html)[:12]:
        js_url = urljoin(page_url, src)
        try:
            _collect(requests.get(js_url, headers=headers, timeout=timeout).text, js_url)
        except Exception:  # noqa: BLE001
            continue

    out: list[str] = []
    for u in found:
        u = u.rstrip("\\'\",);")
        if u not in out:
            out.append(u)
    return out


class FrameGrabber:
    """统一抽帧接口：OpenCV 直读 / ffmpeg 管道 / 本地文件 / 摄像头。"""

    def __init__(self, url: str, backend: str = "auto",
                 fps: float = 0.5, roi: list[float] | None = None,
                 user_agent: str = ""):
        self.url = str(url or "").strip()
        self.fps = max(0.1, float(fps or 0.5))
        self.roi = roi
        self.user_agent = user_agent
        self.cap: Any = None
        self.proc: Any = None
        self._buf = b""
        self._index = 0
        self._lock = threading.Lock()
        self.error = ""
        self.backend = backend
        if backend == "auto":
            self.backend = "ffmpeg" if shutil.which("ffmpeg") else "cv2"

    def open(self) -> bool:
        if not self.url:
            self.error = "未配置 stream_url"
            return False
        try:
            if self.backend == "ffmpeg":
                cmd = [
                    "ffmpeg", "-loglevel", "error", "-nostdin",
                    "-user_agent", self.user_agent or "Mozilla/5.0",
                    "-i", self.url, "-an",
                    "-vf", f"fps={self.fps}", "-f", "image2pipe",
                    "-vcodec", "mjpeg", "-q:v", "4", "pipe:1",
                ]
                self.proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
                return self.proc.poll() is None
            # cv2：数字视为摄像头编号
            target: Any = int(self.url) if self.url.isdigit() else self.url
            self.cap = cv2.VideoCapture(target)
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:  # noqa: BLE001
                pass
            return bool(self.cap.isOpened())
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            return False

    def _next_jpeg(self) -> bytes | None:
        assert self.proc and self.proc.stdout
        while True:
            start = self._buf.find(b"\xff\xd8")
            if start >= 0:
                end = self._buf.find(b"\xff\xd9", start + 2)
                if end >= 0:
                    jpg = self._buf[start:end + 2]
                    self._buf = self._buf[end + 2:]
                    return jpg
            chunk = self.proc.stdout.read(8192)
            if not chunk:
                return None
            self._buf += chunk
            if len(self._buf) > 12 * 1024 * 1024:
                self._buf = self._buf[-2 * 1024 * 1024:]

    def _crop(self, image: Any) -> Any:
        if not self.roi or len(self.roi) != 4:
            return image
        h, w = image.shape[:2]
        x1, y1, x2, y2 = [float(v) for v in self.roi]
        return image[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]

    def read(self) -> Frame | None:
        with self._lock:
            raw: Any = None
            if self.backend == "ffmpeg":
                jpg = self._next_jpeg()
                if jpg:
                    raw = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            elif self.cap is not None:
                ok, raw = self.cap.read()
                if not ok:
                    raw = None
            if raw is None:
                return None
            self._index += 1
            return Frame(self._crop(raw), time.time(), self._index)

    def close(self) -> None:
        with self._lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            if self.proc is not None:
                try:
                    self.proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                self.proc = None
