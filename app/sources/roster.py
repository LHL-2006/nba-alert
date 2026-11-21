"""球员名单索引：id / 姓名 / 姓氏 / 球衣号码 -> 球员。

数据层的 participants 只给 athlete id，画面 OCR 给的是号码或姓名，
统一靠这个索引做身份归并。"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any


def _norm(s: str) -> str:
    """归一化用于匹配：小写、标点转空格、压缩空白。"""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", (s or "").lower())).strip()


@dataclass(frozen=True)
class RosterEntry:
    id: str
    name: str
    jersey: str = ""
    team_id: str = ""
    team_abbrev: str = ""

    @property
    def last_name(self) -> str:
        parts = (self.name or "").split()
        return parts[-1] if parts else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "jersey": self.jersey,
            "team_id": self.team_id, "team_abbrev": self.team_abbrev,
        }


@dataclass
class NameHit:
    entry: RosterEntry
    start: int
    end: int


class RosterIndex:
    def __init__(self, entries: list[RosterEntry] | None = None):
        self.entries: list[RosterEntry] = [e for e in (entries or []) if e.name]
        self.by_id: dict[str, RosterEntry] = {e.id: e for e in self.entries if e.id}
        self._by_norm: dict[str, RosterEntry] = {}
        self._by_last: dict[str, list[RosterEntry]] = {}
        self._by_jersey: dict[str, list[RosterEntry]] = {}
        for e in self.entries:
            self._by_norm.setdefault(_norm(e.name), e)
            last = _norm(e.last_name)
            if last:
                self._by_last.setdefault(last, []).append(e)
            if e.jersey:
                key = e.jersey.lstrip("0") or "0"
                self._by_jersey.setdefault(key, []).append(e)

    # ---------- 查询 ----------
    def lookup(self, name: str) -> RosterEntry | None:
        n = _norm(name)
        if not n:
            return None
        if n in self._by_norm:
            return self._by_norm[n]
        if n in self._by_last:
            hits = self._by_last[n]
            if len(hits) == 1:
                return hits[0]
        close = difflib.get_close_matches(n, list(self._by_norm), n=1, cutoff=0.86)
        return self._by_norm[close[0]] if close else None

    def by_jersey(self, number: str | int, team_abbrev: str = "") -> list[RosterEntry]:
        key = str(number).lstrip("0") or "0"
        hits = self._by_jersey.get(key, [])
        if team_abbrev:
            narrowed = [e for e in hits if e.team_abbrev.upper() == team_abbrev.upper()]
            if narrowed:
                return narrowed
        return hits

    def match_text(self, text: str) -> list[NameHit]:
        """在一段 OCR / 逐回合文本里找出所有出现的球员名（全名优先，其次姓氏）。"""
        t = _norm(text)
        hits: list[NameHit] = []
        for n, entry in self._by_norm.items():
            if len(n) < 3:
                continue
            start = t.find(n)
            while start != -1:
                end = start + len(n)
                left_ok = start == 0 or not t[start - 1].isalnum()
                right_ok = end >= len(t) or not t[end].isalnum()
                if left_ok and right_ok:
                    hits.append(NameHit(entry, start, end))
                start = t.find(n, start + 1)
        for last, entries in self._by_last.items():
            if len(last) < 4:
                continue
            for m in re.finditer(r"\b" + re.escape(last) + r"\b", t):
                if any(h.start <= m.start() and h.end >= m.end() for h in hits):
                    continue
                hits.append(NameHit(entries[0], m.start(), m.end()))
        hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
        # 去掉被更长匹配覆盖的重叠项
        kept: list[NameHit] = []
        for h in hits:
            if any(k.start <= h.start and k.end >= h.end and k is not h for k in kept):
                continue
            kept.append(h)
        return kept

    def __len__(self) -> int:
        return len(self.entries)

    # ---------- 构造器 ----------
    @classmethod
    def from_espn(cls, summary: dict[str, Any]) -> "RosterIndex":
        entries: list[RosterEntry] = []
        for block in summary.get("boxscore", {}).get("players", []) or []:
            team = block.get("team", {}) or {}
            tid = str(team.get("id", "") or "")
            abbr = str(team.get("abbreviation", "") or "")
            for group in block.get("statistics", []) or []:
                labels = [str(x).lower() for x in (group.get("labels") or group.get("names") or [])]
                for row in group.get("athletes", []) or []:
                    a = row.get("athlete", {}) or {}
                    name = (a.get("displayName") or a.get("fullName")
                            or a.get("shortName") or "")
                    jersey = str(a.get("jersey", "") or "")
                    if not jersey:
                        for k, v in zip(labels, row.get("stats") or []):
                            if k in ("jersey", "number", "num", "#"):
                                jersey = str(v or "")
                                break
                    if name:
                        entries.append(RosterEntry(str(a.get("id", "") or ""), name,
                                                   jersey, tid, abbr))
        return cls(entries)

    @classmethod
    def from_nba_boxscore(cls, data: dict[str, Any]) -> "RosterIndex":
        entries: list[RosterEntry] = []
        game = data.get("game", {}) or {}
        for side in ("homeTeam", "awayTeam"):
            t = game.get(side, {}) or {}
            tid = str(t.get("teamId", "") or "")
            abbr = str(t.get("teamTricode") or t.get("teamAbbreviation") or "")
            for p in t.get("players", []) or []:
                name = (p.get("name") or " ".join(
                    str(x) for x in (p.get("firstName"), p.get("familyName")) if x))
                jersey = str(p.get("jerseyNum", "") or "").lstrip("0") or "0"
                if name:
                    entries.append(RosterEntry(str(p.get("personId", "") or ""),
                                               name, jersey, tid, abbr))
        return cls(entries)
