"""轮询编排：双源自动降级 + 按场次预热 + 增量去重。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..models import GameInfo, PlayEvent, PlayerPresence
from .base import LiveDataSource
from .espn_source import ESPNSource
from .nba_api_source import NBAAPISource
from .roster import RosterIndex

log = logging.getLogger(__name__)


@dataclass
class PollResult:
    games: list[GameInfo] = field(default_factory=list)
    events: list[PlayEvent] = field(default_factory=list)
    rosters: dict[str, RosterIndex] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)
    # 演示源可直接给出现在场快照；真实模式由 VisionWorker 回调填充
    presence: list[PlayerPresence] = field(default_factory=list)


class SourceManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.sources: dict[str, LiveDataSource] = {
            "nba_api": NBAAPISource(cfg),
            "espn": ESPNSource(cfg),
        }
        self.fail_count = 0
        self.threshold = max(1, int(cfg.get("data_source.fail_threshold", 2)))
        self.seen: set[str] = set()
        self.warmed_games: set[str] = set()
        self.games: dict[str, GameInfo] = {}
        self.rosters: dict[str, RosterIndex] = {}
        self.polls = 0
        self.events_total = 0
        self.last_error = ""
        self.last_poll = 0.0
        self._select_initial()

    def _select_initial(self) -> None:
        prefer = str(self.cfg.get("data_source.prefer", "auto")).lower()
        if prefer == "espn":
            self.active = self.sources["espn"]
            self.probe_msg = "配置指定 ESPN"
        elif prefer == "nba_api":
            self.active = self.sources["nba_api"]
            self.probe_msg = "配置指定 nba_api"
        else:
            ok, msg = self.sources["nba_api"].health()
            if ok:
                self.active = self.sources["nba_api"]
                self.probe_msg = f"nba_api 探测通过：{msg}"
            else:
                self.active = self.sources["espn"]
                self.probe_msg = f"nba_api 不可用，自动降级 ESPN（{msg}）"
        log.info("数据源选择: %s | %s", self.active.name, self.probe_msg)

    def _switch(self, reason: str) -> None:
        other = "espn" if self.active.name != "espn" else "nba_api"
        log.warning("切换数据源 %s -> %s：%s", self.active.name, other, reason)
        self.active = self.sources[other]
        self.fail_count = 0
        self.warmed_games.clear()   # 新源 id 空间不同，重新预热避免刷屏
        self.last_error = f"已切换至 {other}：{reason}"

    def poll(self) -> PollResult:
        date = self.cfg.get("app.date") or None
        result = PollResult()
        try:
            games = self.active.fetch_games(date)
            result.games = games
            self.games = {g.game_id: g for g in games}

            targets = [g for g in games if g.status == "in"]
            if not targets and games:
                # 没有进行中比赛时，取最后一场用于面板预览/回放验证
                targets = [games[-1]]

            for g in targets:
                updated, events, roster = self.active.fetch_game(g)
                self.games[g.game_id] = updated
                self.rosters[g.game_id] = roster
                result.rosters[g.game_id] = roster
                warm = g.game_id not in self.warmed_games
                for e in events:
                    if warm:
                        self.seen.add(e.dedup_key)   # 首轮只预热，不推送历史
                        continue
                    if e.dedup_key not in self.seen:
                        self.seen.add(e.dedup_key)
                        result.events.append(e)
                self.warmed_games.add(g.game_id)

            self.fail_count = 0
            self.last_error = ""
        except Exception as exc:  # noqa: BLE001
            self.fail_count += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("轮询失败(%d/%d): %s", self.fail_count, self.threshold, self.last_error)
            if self.fail_count >= self.threshold:
                self._switch(self.last_error)
            result.games = list(self.games.values())

        # 防止 seen 无限增长
        if len(self.seen) > 20000:
            keep = set(list(self.seen)[-8000:])
            self.seen = keep
            self.warmed_games.clear()

        self.polls += 1
        self.events_total += len(result.events)
        self.last_poll = time.time()
        result.status = self.status()
        return result

    def status(self) -> dict[str, Any]:
        return {
            "source": self.active.name,
            "probe": self.probe_msg,
            "polls": self.polls,
            "events_total": self.events_total,
            "last_poll": self.last_poll,
            "last_error": self.last_error,
            "fail_count": self.fail_count,
            "live_games": sum(1 for g in self.games.values() if g.status == "in"),
            "roster_size": sum(len(r) for r in self.rosters.values()),
        }
