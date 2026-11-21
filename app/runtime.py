"""运行时中枢：数据层 + 视觉层 + 规则引擎 + 推送 + WebSocket 广播。"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import time
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from .config import Config
from .engine import AlertEngine
from .models import GameInfo, PlayEvent, PlayerPresence
from .notifiers.base import build_notifiers
from .sources.demo import DemoSource
from .sources.manager import PollResult, SourceManager
from .sources.roster import RosterIndex
from .state import StateStore
from .vision.worker import VisionWorker

log = logging.getLogger(__name__)
# 源码模式落在项目目录；打包后由 launcher 设置 NBA_ALERT_HOME 落在 exe 同目录
_HOME = Path(os.environ.get("NBA_ALERT_HOME") or Path(__file__).resolve().parent.parent)
STATE_PATH = _HOME / "data" / "state.json"


class Runtime:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.demo = bool(cfg.get("app.demo_mode", False))
        self.source: Any = DemoSource(cfg) if self.demo else SourceManager(cfg)
        self.state = StateStore(str(STATE_PATH))
        self.notifiers = build_notifiers(cfg)
        self.engine = AlertEngine(cfg, self.state, self.notifiers)

        self.games: dict[str, GameInfo] = {}
        self.rosters: dict[str, RosterIndex] = {}
        self.source_status: dict[str, Any] = {}
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._vision_events: queue.Queue[list[PlayEvent]] = queue.Queue()

        self.vision = VisionWorker(
            cfg,
            on_events=self._on_vision_events,
            on_presence=self._on_presence,
            roster_provider=self._current_roster,
            game_id_provider=self._current_game_id,
        )

    # ---------- 视觉线程回调（非 event loop 线程） ----------
    def _current_roster(self) -> RosterIndex:
        return next(iter(self.rosters.values())) if self.rosters else RosterIndex()

    def _current_game_id(self) -> str:
        return next(iter(self.games), "")

    def _on_vision_events(self, events: list[PlayEvent]) -> None:
        self._vision_events.put(events)

    def _on_presence(self, presence: list[PlayerPresence]) -> None:
        self.state.set_presence(presence)
        self._publish_sync({"type": "presence",
                            "data": [p.to_dict() for p in presence]})

    def _publish_sync(self, msg: dict[str, Any]) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.broadcast(msg)))

    # ---------- 生命周期 ----------
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.vision.start()
        self._task = asyncio.create_task(self._poll_loop(), name="nba-poll")
        log.info("运行时已启动：demo=%s, notifiers=%s",
                 self.demo, [n.name for n in self.notifiers])

    async def stop(self) -> None:
        self.vision.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.state.save()

    # ---------- 主循环 ----------
    async def _poll_loop(self) -> None:
        interval = max(2.0, float(self.cfg.get("app.poll_interval_sec", 8)))
        while True:
            try:
                result: PollResult = await asyncio.to_thread(self.source.poll)
                await self._handle(result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("主循环异常: %s", exc)
                self.source_status["last_error"] = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(interval)

    async def _handle(self, result: PollResult) -> None:
        for g in result.games:
            self.games[g.game_id] = g
        self.rosters.update(result.rosters)
        self.source_status = result.status
        if result.presence:
            self.state.set_presence(result.presence)
            await self.broadcast({
                "type": "presence",
                "data": [p.to_dict() for p in result.presence],
            })

        vision_events: list[PlayEvent] = []
        while True:
            try:
                vision_events.extend(self._vision_events.get_nowait())
            except queue.Empty:
                break

        proc = await asyncio.to_thread(
            self.engine.process, result.events + vision_events, dict(self.games))
        for e in proc.watched_events:
            await self.broadcast({"type": "event", "data": e.to_dict()})
        for a in proc.alerts:
            await self.broadcast({"type": "alert", "data": a.to_dict()})
        await self.broadcast({"type": "status", "data": self.status_snapshot()})

    # ---------- WebSocket ----------
    async def add_client(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        await ws.send_json({"type": "status", "data": self.status_snapshot()})
        await ws.send_json({"type": "history", "data": self.state.snapshot()})

    def remove_client(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, msg: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    # ---------- 对外状态 ----------
    def status_snapshot(self) -> dict[str, Any]:
        return {
            "source": self.source_status or {"source": self.source.name, "probe": "启动中"},
            "vision": dict(self.vision.status),
            "games": [g.to_dict() for g in self.games.values()],
            "presence": [p.to_dict() for p in self.state.presence],
            "notifiers": [{"name": n.name, "enabled": bool(n.enabled)}
                          for n in self.notifiers],
            "watch": self.cfg.watch_players,
            "demo": self.demo,
            "clients": len(self.clients),
            "server_time": time.time(),
        }
