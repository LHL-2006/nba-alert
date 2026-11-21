"""规则引擎单元测试：过滤、去重、冷却、通道调用。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config  # noqa: E402
from app.engine import AlertEngine  # noqa: E402
from app.models import Alert, EventType, PlayEvent  # noqa: E402
from app.notifiers.base import Notifier  # noqa: E402
from app.state import StateStore  # noqa: E402


class DummyNotifier(Notifier):
    name = "dummy"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.sent: list[Alert] = []

    def send(self, alert: Alert) -> str:
        self.sent.append(alert)
        return "ok"


def cfg_with(events: list[str], cooldown: int = 0) -> Config:
    cfg = Config.load(str(Path(__file__).resolve().parent.parent / "config.yaml"))
    cfg.set("watch.players", [{
        "name": "LeBron James", "aliases": ["詹姆斯", "LBJ"],
        "jersey": "23", "team": "LAL", "events": events,
    }])
    cfg.set("watch.cooldown_sec", cooldown)
    return cfg


def event(etype: EventType, name: str = "LeBron James", eid: str = "e1") -> PlayEvent:
    return PlayEvent(id=eid, game_id="g1", event_type=etype, player_name=name,
                     text=f"test {etype.value}", source="espn", score_value=2)


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = StateStore(str(Path(self.tmp.name) / "state.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_filters_by_subscribed_event(self):
        cfg = cfg_with(["score"])
        n = DummyNotifier(cfg)
        eng = AlertEngine(cfg, self.state, [n])
        r = eng.process([event(EventType.ASSIST), event(EventType.SCORE)], {})
        self.assertEqual(len(r.watched_events), 2)
        self.assertEqual(len(r.alerts), 1)
        self.assertEqual(r.alerts[0].event.event_type, EventType.SCORE)
        self.assertEqual(len(n.sent), 1)

    def test_ignores_unwatched_player(self):
        cfg = cfg_with(["score"])
        eng = AlertEngine(cfg, self.state, [DummyNotifier(cfg)])
        r = eng.process([event(EventType.SCORE, "Stephen Curry")], {})
        self.assertEqual(len(r.watched_events), 0)
        self.assertEqual(len(r.alerts), 0)

    def test_alias_matching(self):
        cfg = cfg_with(["score"])
        eng = AlertEngine(cfg, self.state, [DummyNotifier(cfg)])
        r = eng.process([event(EventType.SCORE, "詹姆斯")], {})
        self.assertEqual(len(r.alerts), 1)

    def test_dedup(self):
        cfg = cfg_with(["score"])
        n = DummyNotifier(cfg)
        eng = AlertEngine(cfg, self.state, [n])
        eng.process([event(EventType.SCORE, eid="same")], {})
        eng.process([event(EventType.SCORE, eid="same")], {})
        self.assertEqual(len(n.sent), 1)

    def test_cooldown(self):
        cfg = cfg_with(["score"], cooldown=3600)
        n = DummyNotifier(cfg)
        eng = AlertEngine(cfg, self.state, [n])
        eng.process([event(EventType.SCORE, eid="a")], {})
        eng.process([event(EventType.SCORE, eid="b")], {})
        self.assertEqual(len(n.sent), 1)

    def test_channel_results_recorded(self):
        cfg = cfg_with(["turnover"])
        n = DummyNotifier(cfg)
        eng = AlertEngine(cfg, self.state, [n])
        r = eng.process([event(EventType.TURNOVER)], {})
        self.assertEqual(r.alerts[0].channels, {"dummy": "ok"})
        self.assertEqual(r.alerts[0].level, "warn")


if __name__ == "__main__":
    unittest.main()
