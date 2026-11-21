"""FastAPI + WebSocket 实时面板服务。"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .config import Config
from .models import EventType, PlayEvent
from .runtime import Runtime
from .vision.stream import probe_m3u8

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class WatchPayload(BaseModel):
    name: str
    aliases: list[str] = []
    jersey: str = ""
    team: str = ""
    action: str = "add"          # add | remove
    events: list[str] = []


def create_app(cfg: Config) -> FastAPI:
    runtime = Runtime(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.start()
        yield
        await runtime.stop()

    app = FastAPI(title="NBA 关注球员实时提醒面板", version="1.0.0",
                  lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/status")
    async def status():
        return runtime.status_snapshot()

    @app.get("/api/history")
    async def history(limit: int = Query(100, ge=1, le=300)):
        return runtime.state.snapshot(limit)

    @app.get("/api/probe")
    async def probe(url: str = Query(..., description="直播间页面 URL")):
        if not url.lower().startswith(("http://", "https://")):
            return JSONResponse({"error": "仅支持 http/https URL"}, status_code=400)
        try:
            urls = probe_m3u8(url, user_agent=str(cfg.get("data_source.user_agent", "")))
            return {"page": url, "count": len(urls), "streams": urls}
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"},
                                status_code=502)

    @app.post("/api/watch")
    async def watch(payload: WatchPayload):
        players = [p for p in cfg.watch_players
                   if str(p.get("name", "")).lower() != payload.name.lower()]
        if payload.action == "add":
            item: dict[str, Any] = {
                "name": payload.name,
                "aliases": payload.aliases,
                "jersey": payload.jersey,
                "team": payload.team,
                "events": payload.events or cfg.default_events,
            }
            players.append(item)
        cfg.set("watch.players", players)
        runtime.engine.refresh_watch()
        await runtime.broadcast({"type": "status", "data": runtime.status_snapshot()})
        return {"ok": True, "watch": players}

    @app.post("/api/test")
    async def test_push(name: str = Query("LeBron James")):
        """手动触发一条测试提醒，用于验证推送通道是否配置正确。"""
        game_id = runtime._current_game_id() or "test"
        e = PlayEvent(
            id=f"manual-{int(time.time() * 1000)}",
            game_id=game_id,
            event_type=EventType.SCORE,
            player_name=name,
            text="手动测试：这是一条模拟得分提醒",
            score_value=2, period=4, clock="07:12",
            home_score=102, away_score=99, source="manual",
        )
        proc = await asyncio.to_thread(
            runtime.engine.process, [e], dict(runtime.games))
        for a in proc.alerts:
            await runtime.broadcast({"type": "alert", "data": a.to_dict()})
        return {"ok": True, "alerts": [a.to_dict() for a in proc.alerts]}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await runtime.add_client(ws)
        try:
            while True:
                # 仅用于保持连接 / 接收前端心跳
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            runtime.remove_client(ws)

    return app
