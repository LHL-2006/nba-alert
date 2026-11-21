"""画面工作线程：抓帧 -> OCR -> 在场状态，回调产出事件。"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable

from ..config import Config
from ..models import PlayEvent, PlayerPresence
from ..sources.roster import RosterIndex
from .ocr import NullOCREngine, create_engine
from .presence import PresenceConfig, PresenceTracker
from .stream import FrameGrabber

log = logging.getLogger(__name__)


class VisionWorker(threading.Thread):
    def __init__(
        self,
        cfg: Config,
        on_events: Callable[[list[PlayEvent]], None],
        on_presence: Callable[[list[PlayerPresence]], None],
        roster_provider: Callable[[], RosterIndex],
        game_id_provider: Callable[[], str],
    ):
        super().__init__(daemon=True, name="vision-worker")
        self.cfg = cfg
        self.on_events = on_events
        self.on_presence = on_presence
        self.roster_provider = roster_provider
        self.game_id_provider = game_id_provider
        self._stop = threading.Event()
        self.queue: queue.Queue = queue.Queue()
        self.status: dict[str, Any] = {
            "enabled": False, "backend": "", "frames": 0,
            "error": "", "last_frame_ts": 0.0, "stream_url": "",
        }

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        url = str(self.cfg.get("vision.stream_url") or "").strip()
        if not self.cfg.get("vision.enabled", True) or not url:
            self.status["error"] = ("未配置 vision.stream_url，画面模块停用；"
                                    "上场判定回退到数据层换人事件")
            log.info(self.status["error"])
            return
        self.status.update(enabled=True, stream_url=url,
                           backend=str(self.cfg.get("vision.grabber", "auto")))

        engine = create_engine(str(self.cfg.get("vision.ocr_backend", "rapidocr")))
        if isinstance(engine, NullOCREngine):
            self.status["error"] = f"OCR 不可用：{engine.reason}"
            log.warning(self.status["error"])
            return

        grabber = FrameGrabber(
            url,
            backend=str(self.cfg.get("vision.grabber", "auto")),
            fps=float(self.cfg.get("vision.fps", 0.5)),
            roi=self.cfg.get("vision.roi"),
            user_agent=str(self.cfg.get("data_source.user_agent", "")),
        )
        if not grabber.open():
            self.status["error"] = f"打开流失败：{grabber.error or '未知原因'}"
            log.warning(self.status["error"])
            return
        self.status["backend"] = f"{grabber.backend} / {engine.name}"

        pcfg = PresenceConfig.from_cfg(self.cfg)
        tracker = PresenceTracker(pcfg, self.cfg.watch_players,
                                  self.game_id_provider() or "")
        interval = 1.0 / max(0.1, float(self.cfg.get("vision.fps", 0.5)))
        empty_streak = 0

        try:
            while not self._stop.is_set():
                frame = grabber.read()
                if frame is None:
                    empty_streak += 1
                    if empty_streak >= 10:
                        self.status["error"] = "连续读帧失败，尝试重连"
                        grabber.close()
                        if not grabber.open():
                            time.sleep(3)
                            continue
                        empty_streak = 0
                    time.sleep(interval)
                    continue
                empty_streak = 0
                self.status["frames"] += 1
                self.status["last_frame_ts"] = frame.ts
                self.status["error"] = ""
                try:
                    hits = engine.recognize(frame.image)
                    tracker.game_id = self.game_id_provider() or tracker.game_id
                    events = tracker.update(hits, self.roster_provider())
                    if events:
                        self.on_events(events)
                    self.on_presence(tracker.snapshot())
                except Exception as exc:  # noqa: BLE001
                    log.warning("OCR 帧处理异常: %s", exc)
                self._stop.wait(interval)
        finally:
            grabber.close()
            log.info("画面工作线程已退出，共处理 %d 帧", self.status["frames"])
