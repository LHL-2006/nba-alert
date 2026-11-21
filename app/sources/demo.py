"""演示数据源：不访问网络，回放内置样本，用于立即验证完整链路。"""
from __future__ import annotations

import time

from ..config import Config
from ..models import EventType, GameInfo, PlayEvent, PlayerPresence, Team
from .classifier import classify_play
from .manager import PollResult
from .roster import RosterEntry, RosterIndex

DEMO_ROSTER = RosterIndex([
    RosterEntry("1", "LeBron James", "23", "1", "LAL"),
    RosterEntry("2", "Stephen Curry", "30", "2", "GSW"),
    RosterEntry("3", "Anthony Davis", "3", "1", "LAL"),
    RosterEntry("4", "Draymond Green", "23", "2", "GSW"),
    RosterEntry("5", "Rui Hachimura", "28", "1", "LAL"),
    RosterEntry("6", "Klay Thompson", "11", "2", "GSW"),
])

DEMO_GAME = GameInfo(
    game_id="demo:LAL-GSW",
    home=Team("1", "Los Angeles Lakers", "LAL"),
    away=Team("2", "Golden State Warriors", "GSW"),
    status="in", period=4, clock="07:12",
    home_score=102, away_score=99,
    detail="Q4 7:12", source="demo",
)

DEMO_PLAYS: list[str] = [
    "LeBron James enters the game for Rui Hachimura",
    "Stephen Curry makes 27-foot three point jumper (Draymond Green assists)",
    "LeBron James makes 2-foot driving layup (Anthony Davis assists)",
    "Stephen Curry bad pass turnover (LeBron James steals)",
    "LeBron James defensive rebound",
    "Stephen Curry makes free throw 1 of 2",
    "LeBron James blocks Klay Thompson's driving layup",
    "LeBron James makes 25-foot three point jumper",
    "Draymond Green enters the game for Klay Thompson",
    "Stephen Curry makes 30-foot three point jumper (Draymond Green assists)",
    "LeBron James lost ball turnover (Draymond Green steals)",
    "Anthony Davis makes 1-foot dunk (LeBron James assists)",
]


class DemoSource:
    name = "demo"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.i = 0
        self.cycle = 0
        self.last_on_court = False

    def poll(self) -> PollResult:
        text = DEMO_PLAYS[self.i % len(DEMO_PLAYS)]
        self.i += 1
        if self.i % len(DEMO_PLAYS) == 0:
            self.cycle += 1
        period = 4
        clock = f"{7 - (self.i // 5)}:{12 + (self.i * 7) % 48:02d}"
        play = {
            "id": f"demo-{self.i}",
            "text": text,
            "period": period,
            "clock": clock,
            "scoringPlay": " makes " in text,
            "score_value": 3 if "three point" in text else (1 if "free throw" in text else 2),
            "home_score": 102 + self.i, "away_score": 99 + self.i // 2,
            "participants": [], "ts": time.time(),
        }
        events = classify_play(play, DEMO_GAME, DEMO_ROSTER, "demo")

        # 每 4 拍模拟一次画面 OCR 上场/离场翻转
        if self.i % 4 == 0:
            self.last_on_court = not self.last_on_court
            events.append(PlayEvent(
                id=f"vision-{self.i}",
                game_id=DEMO_GAME.game_id,
                event_type=EventType.ON_COURT if self.last_on_court else EventType.OFF_COURT,
                player_name="LeBron James",
                text="OCR 命中球衣 #23" if self.last_on_court else "连续多帧未检出 #23",
                source="vision", confidence=0.86,
                period=period, clock=clock,
            ))

        presence = [
            PlayerPresence(
                player_name="LeBron James",
                on_court=self.last_on_court,
                confidence=0.86 if self.last_on_court else 0.10,
                votes=5 if self.last_on_court else 0, window=6,
                last_seen=time.time(),
                evidence="演示：OCR 命中球衣 #23" if self.last_on_court else "演示：连续未检出 #23",
                source="vision",
            ),
            PlayerPresence(
                player_name="Stephen Curry", on_court=True, confidence=0.72,
                votes=4, window=6, last_seen=time.time(),
                evidence="演示：OCR 命中球衣 #30", source="vision",
            ),
        ]
        return PollResult(
            games=[DEMO_GAME],
            events=events,
            rosters={DEMO_GAME.game_id: DEMO_ROSTER},
            presence=presence,
            status={"source": "demo", "probe": "演示模式", "polls": self.i,
                    "events_total": self.i, "last_poll": time.time(),
                    "last_error": "", "fail_count": 0, "live_games": 1,
                    "roster_size": len(DEMO_ROSTER), "cycle": self.cycle},
        )
