"""画面 OCR 命中 -> 指定球员的「在场 / 离场」判定。

识别策略（三重，任一命中即算一帧命中）：
  1. 球衣号码：OCR 文本里的 1~2 位数字 → roster 号码表 / 配置的 jersey
  2. 姓名：英文名、姓氏、中文别名 → roster / watch.aliases
  3. 转播图文：上场 / enters / check in 等关键词作为证据增强

状态机：滑动窗口投票避免单帧误判；连续 N 帧未命中才判离场。
"""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..models import EventType, PlayEvent, PlayerPresence
from ..sources.roster import RosterIndex
from .ocr import OCRHit

log = logging.getLogger(__name__)

NUMBER_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")
ON_COURT_WORDS = ("enters", "check in", "checks in", "sub in", "on court",
                  "上场", "出场", "登场", "替补登", "换上")


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


@dataclass
class PresenceConfig:
    vote_window: int = 6
    vote_threshold: int = 3
    absent_frames: int = 8
    min_score: float = 0.55
    jersey_mode: bool = True
    text_mode: bool = True

    @classmethod
    def from_cfg(cls, cfg: Any) -> "PresenceConfig":
        return cls(
            vote_window=max(1, int(cfg.get("vision.vote_window", 6))),
            vote_threshold=max(1, int(cfg.get("vision.vote_threshold", 3))),
            absent_frames=max(1, int(cfg.get("vision.absent_frames", 8))),
            min_score=float(cfg.get("vision.min_score", 0.55)),
            jersey_mode=bool(cfg.get("vision.jersey_mode", True)),
            text_mode=bool(cfg.get("vision.text_mode", True)),
        )


class PresenceTracker:
    def __init__(self, pcfg: PresenceConfig, watch: list[dict[str, Any]],
                 game_id: str = ""):
        self.cfg = pcfg
        self.game_id = game_id
        self.watch = watch
        self.aliases: dict[str, set[str]] = {}
        self.jerseys: dict[str, set[str]] = {}
        for p in watch:
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            al = {_norm(name), _norm(name.split()[-1])}
            al |= {_norm(a) for a in (p.get("aliases") or []) if a}
            self.aliases[name] = {a for a in al if len(a) >= 2}
            j = str(p.get("jersey") or "").strip()
            self.jerseys[name] = {j.lstrip("0") or "0"} if j else set()

        size = max(pcfg.vote_window, pcfg.absent_frames)
        self.history: dict[str, deque[bool]] = {
            name: deque(maxlen=size) for name in self.aliases
        }
        self.state: dict[str, bool] = {name: False for name in self.aliases}
        self.last_seen: dict[str, float] = {}
        self.evidence: dict[str, str] = {}
        self.frames = 0

    def _detect(self, hits: list[OCRHit], roster: RosterIndex) -> dict[str, str]:
        detected: dict[str, str] = {}
        for h in hits:
            if h.score < self.cfg.min_score:
                continue
            t = (h.text or "").strip()
            if not t:
                continue
            low = t.lower()
            boost = any(w in low or w in t for w in ON_COURT_WORDS)

            if self.cfg.jersey_mode:
                for num in NUMBER_RE.findall(t):
                    n = num.lstrip("0") or "0"
                    for name, nums in self.jerseys.items():
                        if n in nums:
                            detected.setdefault(name, f"球衣 #{num}")
                    for e in roster.by_jersey(n):
                        detected.setdefault(e.name, f"球衣 #{num}")

            if self.cfg.text_mode:
                nt = _norm(t)
                for name, alias_set in self.aliases.items():
                    if any(a in nt for a in alias_set):
                        detected.setdefault(name, f"OCR 文本「{t[:32]}」")
                        continue
                for m in roster.match_text(t):
                    detected.setdefault(m.entry.name, f"OCR 姓名「{t[:32]}」")

            if boost:
                for name in list(detected):
                    detected[name] += " + 上场图文"
        return detected

    def update(self, hits: list[OCRHit], roster: RosterIndex) -> list[PlayEvent]:
        detected = self._detect(hits, roster)
        self.frames += 1
        events: list[PlayEvent] = []
        for name, dq in self.history.items():
            hit = name in detected
            dq.append(hit)
            if hit:
                self.last_seen[name] = time.time()
                self.evidence[name] = detected[name]
            recent = list(dq)[-self.cfg.vote_window:]
            votes = sum(recent)
            window = len(recent)

            if not self.state[name]:
                if votes >= self.cfg.vote_threshold and window >= min(3, self.cfg.vote_threshold):
                    self.state[name] = True
                    events.append(self._event(name, True, votes, window))
            else:
                tail = list(dq)[-self.cfg.absent_frames:]
                if len(tail) >= self.cfg.absent_frames and not any(tail):
                    self.state[name] = False
                    events.append(self._event(name, False, 0, window))
        return events

    def _event(self, name: str, on_court: bool, votes: int, window: int) -> PlayEvent:
        conf = votes / window if window else 0.0
        if on_court:
            text = f"画面确认上场（{self.evidence.get(name, '连续多帧命中')}，{votes}/{window} 帧）"
        else:
            text = f"连续 {self.cfg.absent_frames} 帧未检出，判定离场"
        return PlayEvent(
            id=f"vision-{int(time.time() * 1000)}-{_norm(name)}-{int(on_court)}",
            game_id=self.game_id,
            event_type=EventType.ON_COURT if on_court else EventType.OFF_COURT,
            player_name=name,
            text=text,
            source="vision",
            confidence=conf,
        )

    def snapshot(self) -> list[PlayerPresence]:
        out: list[PlayerPresence] = []
        for name, dq in self.history.items():
            recent = list(dq)[-self.cfg.vote_window:]
            out.append(PlayerPresence(
                player_name=name,
                on_court=self.state[name],
                confidence=sum(recent) / len(recent) if recent else 0.0,
                votes=sum(recent),
                window=len(recent),
                last_seen=self.last_seen.get(name, 0.0),
                evidence=self.evidence.get(name, ""),
                source="vision",
            ))
        return out
