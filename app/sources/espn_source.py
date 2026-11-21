"""ESPN 公开实时数据源（无需密钥，国内网络实测可用）。

接口：
  GET /scoreboard?dates=YYYYMMDD        当日赛程与状态
  GET /summary?event=<id>              逐回合 + boxscore + 球员名单
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..models import GameInfo, PlayEvent, Team
from .base import LiveDataSource
from .classifier import classify_play
from .roster import RosterIndex

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


def _ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _state(comp: dict[str, Any]) -> str:
    return str(comp.get("status", {}).get("type", {}).get("state", "pre"))


def _team(raw: dict[str, Any]) -> Team:
    t = raw.get("team", {}) or {}
    return Team(
        id=str(t.get("id", "") or ""),
        name=str(t.get("displayName") or t.get("name") or ""),
        abbreviation=str(t.get("abbreviation") or ""),
    )


def _game_from_event(e: dict[str, Any]) -> GameInfo | None:
    comps = e.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    by_side = {c.get("homeAway"): c for c in comp.get("competitors", []) or []}
    home_raw, away_raw = by_side.get("home"), by_side.get("away")
    if not home_raw or not away_raw:
        return None
    status = comp.get("status", {}) or {}
    try:
        hs = int(home_raw.get("score") or 0)
        aws = int(away_raw.get("score") or 0)
    except (TypeError, ValueError):
        hs, aws = 0, 0
    typ = status.get("type", {}) or {}
    return GameInfo(
        game_id=f"espn:{e.get('id')}",
        home=_team(home_raw), away=_team(away_raw),
        status=_state(comp),
        period=int(status.get("period") or 0),
        clock=str(status.get("displayClock") or ""),
        home_score=hs, away_score=aws,
        detail=str(typ.get("shortDetail") or typ.get("detail") or ""),
        source="espn",
    )


class ESPNSource(LiveDataSource):
    name = "espn"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self.session.get(BASE + path, params=params or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def fetch_games(self, date: str | None = None) -> list[GameInfo]:
        data = self._get("/scoreboard", {"dates": date} if date else {})
        out: list[GameInfo] = []
        for e in data.get("events", []) or []:
            g = _game_from_event(e)
            if g:
                out.append(g)
        return out

    def fetch_game(self, game: GameInfo) -> tuple[GameInfo, list[PlayEvent], RosterIndex]:
        event_id = game.game_id.split(":", 1)[-1]
        data = self._get("/summary", {"event": event_id})

        # 用 header 覆盖比分/状态（比 scoreboard 更实时）
        comps = (data.get("header", {}).get("competitions")
                 or data.get("competitions") or [])
        if comps:
            comp = comps[0]
            status = comp.get("status", {}) or {}
            game.status = _state(comp)
            game.period = int(status.get("period") or game.period)
            game.clock = str(status.get("displayClock") or game.clock)
            typ = status.get("type", {}) or {}
            game.detail = str(typ.get("shortDetail") or typ.get("detail") or game.detail)
            for c in comp.get("competitors", []) or []:
                try:
                    score = int(c.get("score") or 0)
                except (TypeError, ValueError):
                    continue
                if c.get("homeAway") == "home":
                    game.home_score = score
                elif c.get("homeAway") == "away":
                    game.away_score = score

        roster = RosterIndex.from_espn(data)
        events: list[PlayEvent] = []
        for p in data.get("plays", []) or []:
            play = {
                "id": str(p.get("id") or ""),
                "text": p.get("text") or "",
                "period": (p.get("period") or {}).get("number") or 0,
                "clock": (p.get("clock") or {}).get("displayValue") or "",
                "scoringPlay": bool(p.get("scoringPlay")),
                "score_value": int(p.get("scoreValue") or 0),
                "home_score": int(p.get("homeScore") or 0),
                "away_score": int(p.get("awayScore") or 0),
                "participants": [
                    str(x.get("athlete", {}).get("id", ""))
                    for x in (p.get("participants") or [])
                ],
                "ts": _ts(p.get("wallclock")) or None,
            }
            events.extend(classify_play(play, game, roster, self.name))
        return game, events, roster
