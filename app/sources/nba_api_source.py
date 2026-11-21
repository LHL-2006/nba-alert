"""nba_api 主源：NBA 官方 live 端点（cdn.nba.com liveData）。

说明：cdn.nba.com / stats.nba.com 在部分网络（含中国大陆）会被 Akamai 拦截，
因此 SourceManager 会在探测失败时自动降级到 ESPNSource。
本文件仍完整实现，换到可访问的网络即可作为主源使用。
"""
from __future__ import annotations

import re
import time
from typing import Any

import requests

from ..models import GameInfo, PlayEvent, Team
from .base import LiveDataSource
from .classifier import classify_play
from .roster import RosterIndex

CDN = "https://cdn.nba.com/static/json/liveData"
_CLOCK_RE = re.compile(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")


def _clock(value: str) -> str:
    """PT05M30.00S -> 5:30"""
    s = str(value or "")
    m = _CLOCK_RE.match(s)
    if not m:
        return s or ""
    minutes = int(m.group(1) or 0)
    seconds = int(float(m.group(2) or 0))
    return f"{minutes}:{seconds:02d}"


def _status(code: int) -> str:
    return {1: "pre", 2: "in", 3: "post"}.get(int(code or 0), "pre")


def _team(raw: dict[str, Any]) -> Team:
    name = " ".join(str(x) for x in (raw.get("teamCity"), raw.get("teamName")) if x).strip()
    return Team(
        id=str(raw.get("teamId", "") or ""),
        name=name or str(raw.get("teamName") or ""),
        abbreviation=str(raw.get("teamTricode") or raw.get("teamAbbreviation") or ""),
    )


class NBAAPISource(LiveDataSource):
    name = "nba_api"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com",
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true",
        }

    def _scoreboard(self) -> dict[str, Any]:
        from nba_api.live.nba.endpoints.scoreboard import ScoreBoard
        return ScoreBoard().get_dict()

    def _boxscore(self, game_id: str) -> dict[str, Any]:
        from nba_api.live.nba.endpoints.boxscore import BoxScore
        return BoxScore(game_id=game_id).get_dict()

    def _actions(self, game_id: str) -> list[dict[str, Any]]:
        """优先 nba_api 的 playbyplay endpoint，缺失/失败时直连官方 CDN。"""
        try:
            from nba_api.live.nba.endpoints.playbyplay import PlayByPlay  # type: ignore
            data = PlayByPlay(game_id=game_id).get_dict()
            actions = (data.get("game") or {}).get("actions") or []
            if actions:
                return actions
        except Exception:  # noqa: BLE001
            pass
        url = f"{CDN}/playbyplay/playbyplay_{game_id}.json"
        r = requests.get(url, headers=self._headers, timeout=self.timeout)
        r.raise_for_status()
        return (r.json().get("game") or {}).get("actions") or []

    def health(self) -> tuple[bool, str]:
        """快速探测：直接打 CDN liveData（nba_api 内部请求无超时，避免启动卡住）。

        Akamai 在受限网络下会返回 HTML 403，必须校验响应体确实是 JSON。
        """
        url = f"{CDN}/scoreboard/todaysScoreboard_00.json"
        try:
            r = requests.get(url, headers=self._headers,
                             timeout=min(6, self.timeout))
            body = (r.text or "").lstrip()
            if r.status_code == 200 and body.startswith("{"):
                return True, "CDN liveData 可达"
            return False, f"HTTP {r.status_code}，响应非 JSON（可能被 Akamai 拦截）"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    def fetch_games(self, date: str | None = None) -> list[GameInfo]:
        data = self._scoreboard()
        games: list[GameInfo] = []
        for g in ((data.get("scoreboard") or {}).get("games") or []):
            home, away = g.get("homeTeam") or {}, g.get("awayTeam") or {}
            if not home or not away:
                continue
            games.append(GameInfo(
                game_id=f"nba:{g.get('gameId')}",
                home=_team(home), away=_team(away),
                status=_status(g.get("gameStatus")),
                period=int(g.get("period") or 0),
                clock=_clock(g.get("gameClock")),
                home_score=int(home.get("score") or 0),
                away_score=int(away.get("score") or 0),
                detail=str(g.get("gameStatusText") or ""),
                source=self.name,
            ))
        return games

    def fetch_game(self, game: GameInfo) -> tuple[GameInfo, list[PlayEvent], RosterIndex]:
        gid = game.game_id.split(":", 1)[-1]
        box = self._boxscore(gid)
        bg = box.get("game") or {}
        for side in ("homeTeam", "awayTeam"):
            t = bg.get(side) or {}
            try:
                score = int(t.get("score") or 0)
            except (TypeError, ValueError):
                continue
            if side == "homeTeam":
                game.home_score = score
            else:
                game.away_score = score
        game.period = int(bg.get("period") or game.period)
        game.clock = _clock(bg.get("gameClock")) or game.clock
        game.status = _status(bg.get("gameStatus")) if bg.get("gameStatus") else game.status

        roster = RosterIndex.from_nba_boxscore(box)
        events: list[PlayEvent] = []
        for idx, a in enumerate(self._actions(gid)):
            desc = str(a.get("description") or "")
            atype = str(a.get("actionType") or "").lower()
            made = "made" in atype or bool(re.search(r"\(\d+\s+PTS\)", desc))
            low = desc.lower()
            pts = 0
            if made:
                pts = 3 if "3pt" in low else (1 if "free throw" in low else 2)
            if "substitution" in atype or desc.upper().startswith("SUB:"):
                person = roster.by_id.get(str(a.get("personId", "")))
                who = person.name if person else ""
                desc = f"SUB: {who} FOR Unknown" if who else desc
            play = {
                "id": str(a.get("actionNumber") or a.get("actionId") or idx),
                "text": desc,
                "period": int(a.get("period") or 0),
                "clock": _clock(a.get("clock")),
                "scoringPlay": made,
                "score_value": pts,
                "home_score": int(a.get("homeScore") or 0),
                "away_score": int(a.get("awayScore") or 0),
                "participants": [str(a["personId"])] if a.get("personId") else [],
                "ts": time.time(),
            }
            events.extend(classify_play(play, game, roster, self.name))
        return game, events, roster
