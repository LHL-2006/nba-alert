"""状态存储：已推送事件持久化（跨重启去重）+ 内存历史环形队列。"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .models import Alert, PlayEvent, PlayerPresence

log = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: str = "data/state.json", max_history: int = 300,
                 ttl_sec: int = 7 * 24 * 3600):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_sec
        self._lock = threading.Lock()
        self.seen: dict[str, float] = {}
        self.events: deque[PlayEvent] = deque(maxlen=max_history)
        self.alerts: deque[Alert] = deque(maxlen=max_history)
        self.presence: list[PlayerPresence] = []
        self._dirty = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            cutoff = time.time() - self.ttl
            self.seen = {k: float(v) for k, v in (data.get("seen") or {}).items()
                         if float(v) > cutoff}
        except Exception as exc:  # noqa: BLE001
            log.warning("读取状态文件失败（已忽略）: %s", exc)

    def is_seen(self, key: str) -> bool:
        with self._lock:
            return key in self.seen

    def mark(self, key: str) -> None:
        with self._lock:
            self.seen[key] = time.time()
            self._dirty += 1
            if self._dirty >= 10:
                self._save_locked()

    def _save_locked(self) -> None:
        try:
            cutoff = time.time() - self.ttl
            self.seen = {k: v for k, v in self.seen.items() if v > cutoff}
            self.path.write_text(
                json.dumps({"seen": self.seen}, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = 0
        except Exception as exc:  # noqa: BLE001
            log.warning("写入状态文件失败: %s", exc)

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    def add_event(self, event: PlayEvent) -> None:
        with self._lock:
            self.events.append(event)

    def add_alert(self, alert: Alert) -> None:
        with self._lock:
            self.alerts.append(alert)

    def set_presence(self, presence: list[PlayerPresence]) -> None:
        with self._lock:
            self.presence = presence

    def snapshot(self, limit: int = 100) -> dict[str, Any]:
        with self._lock:
            events = list(self.events)[-limit:]
            alerts = list(self.alerts)[-limit:]
            presence = list(self.presence)
        return {
            "events": [e.to_dict() for e in reversed(events)],
            "alerts": [a.to_dict() for a in reversed(alerts)],
            "presence": [p.to_dict() for p in presence],
        }
