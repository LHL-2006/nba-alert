"""核心数据模型。所有对外传输的对象都提供 to_dict()。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    # 视觉层判定
    ON_COURT = "on_court"
    OFF_COURT = "off_court"
    # 数据层换人
    SUB_IN = "sub_in"
    SUB_OUT = "sub_out"
    # 规则事件
    SCORE = "score"
    ASSIST = "assist"
    TURNOVER = "turnover"
    REBOUND = "rebound"
    STEAL = "steal"
    BLOCK = "block"
    FOUL = "foul"
    OTHER = "other"


EVENT_LABELS: dict[str, str] = {
    "on_court": "画面确认上场",
    "off_court": "画面确认离场",
    "sub_in": "替补上场",
    "sub_out": "被换下",
    "score": "得分",
    "assist": "助攻",
    "turnover": "失误",
    "rebound": "篮板",
    "steal": "抢断",
    "block": "盖帽",
    "foul": "犯规",
    "other": "其他",
}

# 前端事件标签配色（涨/跌不涉及，采用运动面板语义色）
EVENT_COLORS: dict[str, str] = {
    "on_court": "#22c55e",
    "off_court": "#94a3b8",
    "sub_in": "#22c55e",
    "sub_out": "#94a3b8",
    "score": "#ef4444",
    "assist": "#3b82f6",
    "turnover": "#f59e0b",
    "rebound": "#a855f7",
    "steal": "#14b8a6",
    "block": "#8b5cf6",
    "foul": "#64748b",
    "other": "#64748b",
}


@dataclass
class Team:
    id: str
    name: str
    abbreviation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "abbreviation": self.abbreviation}


@dataclass
class GameInfo:
    game_id: str
    home: Team
    away: Team
    status: str = "pre"           # pre | in | post
    period: int = 0
    clock: str = ""
    home_score: int = 0
    away_score: int = 0
    detail: str = ""
    source: str = ""

    @property
    def label(self) -> str:
        return f"{self.away.name} @ {self.home.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "home": self.home.to_dict(),
            "away": self.away.to_dict(),
            "label": self.label,
            "status": self.status,
            "period": self.period,
            "clock": self.clock,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "detail": self.detail,
            "source": self.source,
        }


@dataclass
class PlayEvent:
    id: str
    game_id: str
    event_type: EventType
    player_name: str
    text: str
    player_id: str = ""
    team_id: str = ""
    secondary_player: str = ""
    secondary_player_id: str = ""
    period: int = 0
    clock: str = ""
    score_value: int = 0
    home_score: int = 0
    away_score: int = 0
    source: str = ""              # nba_api | espn | vision | demo
    confidence: float = 1.0
    ts: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return "|".join([
            self.source, self.game_id, self.id,
            self.event_type.value, self.player_name.strip().lower(),
        ])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "event_type": self.event_type.value,
            "event_label": EVENT_LABELS.get(self.event_type.value, self.event_type.value),
            "color": EVENT_COLORS.get(self.event_type.value, "#64748b"),
            "player_name": self.player_name,
            "player_id": self.player_id,
            "team_id": self.team_id,
            "text": self.text,
            "secondary_player": self.secondary_player,
            "period": self.period,
            "clock": self.clock,
            "score_value": self.score_value,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "ts": self.ts,
        }


@dataclass
class PlayerPresence:
    player_name: str
    on_court: bool = False
    confidence: float = 0.0
    votes: int = 0
    window: int = 0
    last_seen: float = 0.0
    evidence: str = ""
    source: str = "vision"

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_name": self.player_name,
            "on_court": self.on_court,
            "confidence": round(self.confidence, 3),
            "votes": self.votes,
            "window": self.window,
            "last_seen": self.last_seen,
            "evidence": self.evidence,
            "source": self.source,
        }


@dataclass
class Alert:
    id: str
    title: str
    body: str
    event: PlayEvent
    level: str = "info"
    created_at: float = field(default_factory=time.time)
    channels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "level": self.level,
            "created_at": self.created_at,
            "channels": self.channels,
            "event": self.event.to_dict(),
        }
