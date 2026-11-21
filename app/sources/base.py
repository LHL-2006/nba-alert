"""数据源抽象接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..config import Config
from ..models import GameInfo, PlayEvent
from .roster import RosterIndex


class LiveDataSource(ABC):
    """所有实时数据源都实现这两个方法；fetch_game 返回该场比赛的全量事件，
    增量去重由 SourceManager 统一负责。"""

    name: str = "base"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.timeout = int(cfg.get("data_source.timeout_sec", 15))
        self.user_agent = cfg.get("data_source.user_agent", "")

    @abstractmethod
    def fetch_games(self, date: str | None = None) -> list[GameInfo]:
        """返回指定比赛日的全部比赛（含未开始/进行中/已结束）。"""

    @abstractmethod
    def fetch_game(self, game: GameInfo) -> tuple[GameInfo, list[PlayEvent], RosterIndex]:
        """返回更新后的比赛状态、全量逐回合事件、球员名单索引。"""

    def health(self) -> tuple[bool, str]:
        """探测该源在当前网络是否可用。"""
        try:
            games = self.fetch_games()
            return True, f"ok ({len(games)} games)"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
