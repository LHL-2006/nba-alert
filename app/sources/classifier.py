"""逐回合文本 -> 结构化事件。

同时兼容两种格式：
  ESPN      "Naz Reid makes 25-foot three point jumper (Brandon Miller assists)"
            "Brandon Miller bad pass turnover (Jalen Johnson steals)"
            "Luguentz Dort enters the game for Aaron Wiggins"
  NBA CDN   "Smith 25' 3PT Jump Shot (11 PTS) (Jones 3 AST)"
            "Smith Bad Pass Turnover (P1.T5) (Jones STEAL)"
            "SUB: Smith FOR Jones"

一条回合可能产生多个事件（得分 + 助攻、失误 + 抢断、换上 + 换下）。
"""
from __future__ import annotations

import re
import time
from typing import Any

from ..models import EventType, GameInfo, PlayEvent
from .roster import RosterIndex

_WS = re.compile(r"\s+")

ASSIST_RE = re.compile(r"\(([^()]+?)\s+assists?\)", re.I)
NBA_AST_RE = re.compile(r"\(([^()]+?)\s+\d+\s+AST\)", re.I)
STEAL_RE = re.compile(r"\(([^()]+?)\s+steals?\)", re.I)
NBA_STL_RE = re.compile(r"\(([^()]+?)\s+STEAL\)", re.I)
ENTER_RE = re.compile(r"^(.+?)\s+enters the game for\s+(.+)$", re.I)
NBA_SUB_RE = re.compile(r"^SUB:\s*(.+?)\s+FOR\s+(.+)$", re.I)
MAKE_RE = re.compile(r"^(.+?)\s+makes?\b", re.I)
PTS_RE = re.compile(r"\((\d+)\s+PTS\)", re.I)
TURNOVER_RE = re.compile(r"\bturnover\b", re.I)
BLOCK_RE = re.compile(r"^(.+?)\s+blocks?\b", re.I)
REBOUND_RE = re.compile(r"^(.+?)\s+(?:offensive|defensive)\s+rebound", re.I)
FOUL_RE = re.compile(
    r"^(.+?)\s+(?:personal|shooting|offensive|loose ball|flagrant|technical|clear path)\s+foul", re.I)
STEAL_STANDALONE = re.compile(r"^(.+?)\s+steals?\b", re.I)
IGNORE_RE = re.compile(
    r"^(?:jump ball|start of|end of|beginning|timeout|official timeout|instant replay|"
    r"period|quarter|game|shot clock|delay|review|technical foul|flagrant foul)", re.I)
NOISE = re.compile(
    r"\b(bad pass|lost ball|traveling|travel|double dribble|offensive foul|kicked ball|"
    r"3-second|backcourt|palming|discontinued dribble|stepping out of bounds|out of bounds|"
    r"turnover|illegal|violation|shot|jumper|layup|dunk|three point|free throw|pts?|ast)\b", re.I)

Player = tuple[str, str, str]  # (name, id, team_id)
EMPTY: Player = ("", "", "")
_Spec = tuple[EventType, Player, Player, int, str]


def norm_text(s: str) -> str:
    return _WS.sub(" ", (s or "").replace("\n", " ")).strip()


def _clean_name(s: str) -> str:
    s = NOISE.sub(" ", s or "")
    s = re.sub(r"[^A-Za-z'\-\. ]", " ", s)
    return _WS.sub(" ", s).strip(" -.,")


def _resolve(candidate: str, roster: RosterIndex) -> Player:
    """把一段可能含动作描述的文本解析成 (姓名, id, team_id)。"""
    c = _clean_name(candidate)
    if not c:
        return EMPTY
    e = roster.lookup(c)
    if e:
        return (e.name, e.id, e.team_id)
    hits = roster.match_text(candidate)
    if hits:
        h = hits[0].entry
        return (h.name, h.id, h.team_id)
    return (c, "", "")


def _first_group(text: str, *patterns: re.Pattern) -> str:
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(1)
    return ""


def _score_value(text: str, play: dict[str, Any]) -> int:
    pts = int(play.get("score_value") or 0)
    if pts > 0:
        return pts
    low = text.lower()
    if "free throw" in low:
        return 1
    if "3pt" in low or "three point" in low or "3-pointer" in low:
        return 3
    return 2


def _build(play: dict[str, Any], game: GameInfo, source: str,
           specs: list[_Spec], roster: RosterIndex) -> list[PlayEvent]:
    out: list[PlayEvent] = []
    base_id = str(play.get("id") or play.get("text") or "")
    ts = float(play.get("ts") or time.time())
    for i, (etype, primary, secondary, pts, note) in enumerate(specs):
        name, pid, tid = primary
        # id 兜底：participants 里的 athlete id
        if not pid and play.get("participants"):
            entry = roster.by_id.get(str(play["participants"][0]))
            if entry:
                name, pid, tid = entry.name, entry.id, entry.team_id
        if not tid and pid:
            entry = roster.by_id.get(pid)
            if entry:
                tid = entry.team_id
        out.append(PlayEvent(
            id=f"{base_id}::{etype.value}::{i}",
            game_id=game.game_id,
            event_type=etype,
            player_name=name,
            text=note,
            player_id=pid,
            team_id=tid,
            secondary_player=secondary[0],
            secondary_player_id=secondary[1],
            period=int(play.get("period") or 0),
            clock=str(play.get("clock") or ""),
            score_value=pts,
            home_score=int(play.get("home_score") or 0),
            away_score=int(play.get("away_score") or 0),
            source=source,
            ts=ts,
            raw={"play_id": base_id},
        ))
    return out


def classify_play(play: dict[str, Any], game: GameInfo,
                  roster: RosterIndex, source: str) -> list[PlayEvent]:
    text = norm_text(play.get("text"))
    if not text or IGNORE_RE.match(text):
        return []

    specs: list[_Spec] = []

    # 1) 换人：上场 + 下场
    m = ENTER_RE.match(text) or NBA_SUB_RE.match(text)
    if m:
        who = _resolve(m.group(1), roster)
        out_player = _resolve(m.group(2), roster)
        if who[0]:
            specs.append((EventType.SUB_IN, who, out_player, 0, text))
        if out_player[0]:
            specs.append((EventType.SUB_OUT, out_player, who, 0, text))
        return _build(play, game, source, specs, roster)

    assister_raw = _first_group(text, ASSIST_RE, NBA_AST_RE)
    stealer_raw = _first_group(text, STEAL_RE, NBA_STL_RE)
    assister = _resolve(assister_raw, roster) if assister_raw else EMPTY
    stealer = _resolve(stealer_raw, roster) if stealer_raw else EMPTY

    # 2) 得分（并派生助攻）
    scorer: Player = EMPTY
    mm = MAKE_RE.match(text)
    if mm:
        scorer = _resolve(mm.group(1), roster)
    elif PTS_RE.search(text) or (play.get("scoringPlay") and "PTS" not in text):
        hits = roster.match_text(text.split("(")[0])
        if hits:
            e = hits[0].entry
            scorer = (e.name, e.id, e.team_id)
    if scorer[0] and (mm or play.get("scoringPlay")):
        pts = _score_value(text, play)
        specs.append((EventType.SCORE, scorer, assister, pts, text))
        if assister[0]:
            specs.append((EventType.ASSIST, assister, scorer, pts, text))
        return _build(play, game, source, specs, roster)

    # 3) 失误（并派生抢断）
    if TURNOVER_RE.search(text):
        head = text.split("turnover")[0].split("(")[0]
        actor = _resolve(head, roster)
        if not actor[0] and play.get("participants"):
            e = roster.by_id.get(str(play["participants"][0]))
            if e:
                actor = (e.name, e.id, e.team_id)
        if actor[0]:
            specs.append((EventType.TURNOVER, actor, stealer, 0, text))
        if stealer[0]:
            specs.append((EventType.STEAL, stealer, actor, 0, text))
        return _build(play, game, source, specs, roster)

    # 4) 盖帽
    mb = BLOCK_RE.match(text)
    if mb:
        b = _resolve(mb.group(1), roster)
        if b[0]:
            specs.append((EventType.BLOCK, b, EMPTY, 0, text))
        return _build(play, game, source, specs, roster)

    # 5) 篮板（球队篮板忽略）
    mr = REBOUND_RE.match(text)
    if mr and "team rebound" not in text.lower():
        r = _resolve(mr.group(1), roster)
        if r[0]:
            specs.append((EventType.REBOUND, r, EMPTY, 0, text))
        return _build(play, game, source, specs, roster)

    # 6) 犯规
    mf = FOUL_RE.match(text)
    if mf:
        f = _resolve(mf.group(1), roster)
        if f[0]:
            specs.append((EventType.FOUL, f, EMPTY, 0, text))
        return _build(play, game, source, specs, roster)

    # 7) 独立抢断
    ms = STEAL_STANDALONE.match(text)
    if ms:
        s = _resolve(ms.group(1), roster)
        if s[0]:
            specs.append((EventType.STEAL, s, EMPTY, 0, text))
        return _build(play, game, source, specs, roster)

    # 其余回合（跳球、暂停、节末等）不产生事件，避免刷屏
    return []
