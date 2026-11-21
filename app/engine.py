"""规则引擎：关注球员匹配 -> 事件订阅过滤 -> 去重/冷却 -> 生成 Alert -> 推送。"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .models import EVENT_LABELS, Alert, GameInfo, PlayEvent
from .notifiers.base import Notifier
from .state import StateStore

log = logging.getLogger(__name__)


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


@dataclass
class ProcessResult:
    alerts: list[Alert] = field(default_factory=list)
    watched_events: list[PlayEvent] = field(default_factory=list)


class AlertEngine:
    def __init__(self, cfg: Config, state: StateStore, notifiers: list[Notifier]):
        self.cfg = cfg
        self.state = state
        self.notifiers = notifiers
        self.cooldown = float(cfg.get("watch.cooldown_sec", 0) or 0)
        self.last_sent: dict[str, float] = {}
        self.refresh_watch()

    def refresh_watch(self) -> None:
        self.watch: list[dict[str, Any]] = self.cfg.watch_players
        self.index: dict[str, str] = {}
        self.by_name: dict[str, dict[str, Any]] = {}
        for p in self.watch:
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            self.by_name[name] = p
            keys = {_norm(name), _norm(name.split()[-1])}
            keys |= {_norm(a) for a in (p.get("aliases") or []) if a}
            for k in keys:
                if len(k) >= 2:
                    self.index.setdefault(k, name)

    def match_player(self, event: PlayEvent) -> dict[str, Any] | None:
        n = _norm(event.player_name)
        if not n:
            return None
        if n in self.index:
            return self.by_name.get(self.index[n])
        for k, name in self.index.items():
            if len(k) >= 4 and (k in n or (len(n) >= 4 and n in k)):
                return self.by_name.get(name)
        return None

    def process(self, events: list[PlayEvent],
                games: dict[str, GameInfo]) -> ProcessResult:
        result = ProcessResult()
        for e in events:
            player = self.match_player(e)
            if not player:
                continue
            result.watched_events.append(e)
            self.state.add_event(e)

            if e.event_type.value not in self.cfg.events_for(player):
                continue
            key = f"alert|{e.dedup_key}"
            if self.state.is_seen(key):
                continue
            if self.cooldown > 0:
                ck = f"{player['name']}|{e.event_type.value}"
                if time.time() - self.last_sent.get(ck, 0.0) < self.cooldown:
                    self.state.mark(key)
                    continue
                self.last_sent[ck] = time.time()

            alert = self._make_alert(e, player, games.get(e.game_id))
            channels: dict[str, str] = {}
            for n in self.notifiers:
                try:
                    channels[n.name] = n.send(alert)
                except Exception as exc:  # noqa: BLE001
                    channels[n.name] = f"error: {type(exc).__name__}: {exc}"
            alert.channels = channels
            self.state.add_alert(alert)
            self.state.mark(key)
            result.alerts.append(alert)
        return result

    def _make_alert(self, e: PlayEvent, player: dict[str, Any],
                    game: GameInfo | None) -> Alert:
        label = EVENT_LABELS.get(e.event_type.value, e.event_type.value)
        title = f"{e.player_name} · {label}"
        if e.score_value:
            title += f" +{e.score_value}"
        match_line = game.label if game else e.game_id
        clock_line = f"Q{e.period} {e.clock}" if e.period else "—"
        src = "画面 OCR" if e.source == "vision" else "实时数据"
        body = "\n".join([
            f"{title}",
            f"比赛：{match_line}",
            f"时间：{clock_line}    比分：{e.away_score} - {e.home_score}",
            f"详情：{e.text}",
            f"来源：{src}（置信度 {e.confidence:.0%}）",
        ])
        hot = {"score", "on_court", "sub_in"}
        warn = {"turnover", "off_court", "sub_out"}
        level = "hot" if e.event_type.value in hot else (
            "warn" if e.event_type.value in warn else "info")
        return Alert(
            id=f"alert-{int(time.time() * 1000)}-{_norm(e.player_name)}-{e.event_type.value}",
            title=title, body=body, event=e, level=level,
        )
