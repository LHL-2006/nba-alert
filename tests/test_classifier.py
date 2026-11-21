"""分类器单元测试：不访问网络。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import EventType, GameInfo, Team  # noqa: E402
from app.sources.classifier import classify_play  # noqa: E402
from app.sources.roster import RosterEntry, RosterIndex  # noqa: E402

ROSTER = RosterIndex([
    RosterEntry("1", "LeBron James", "23", "1", "LAL"),
    RosterEntry("2", "Stephen Curry", "30", "2", "GSW"),
    RosterEntry("3", "Anthony Davis", "3", "1", "LAL"),
    RosterEntry("4", "Draymond Green", "23", "2", "GSW"),
    RosterEntry("5", "Rui Hachimura", "28", "1", "LAL"),
    RosterEntry("6", "Klay Thompson", "11", "2", "GSW"),
])
GAME = GameInfo("test:1", Team("1", "Lakers", "LAL"), Team("2", "Warriors", "GSW"))


def parse(text: str, **kw):
    play = {
        "id": "p1", "text": text, "period": 2, "clock": "08:31",
        "scoringPlay": False, "score_value": 0,
        "home_score": 50, "away_score": 48,
        "participants": [], "ts": 0,
    }
    play.update(kw)
    return classify_play(play, GAME, ROSTER, "test")


def kinds(events) -> list[str]:
    return [e.event_type.value for e in events]


class TestClassifier(unittest.TestCase):
    def test_score_and_assist(self):
        evs = parse("LeBron James makes 25-foot three point jumper (Anthony Davis assists)",
                    scoringPlay=True, score_value=3)
        self.assertEqual(kinds(evs), ["score", "assist"])
        self.assertEqual(evs[0].player_name, "LeBron James")
        self.assertEqual(evs[0].score_value, 3)
        self.assertEqual(evs[1].player_name, "Anthony Davis")
        self.assertEqual(evs[1].secondary_player, "LeBron James")

    def test_turnover_and_steal(self):
        evs = parse("Stephen Curry bad pass\nturnover (LeBron James steals)")
        self.assertEqual(kinds(evs), ["turnover", "steal"])
        self.assertEqual(evs[0].player_name, "Stephen Curry")
        self.assertEqual(evs[1].player_name, "LeBron James")

    def test_substitution(self):
        evs = parse("LeBron James enters the game for Rui Hachimura")
        self.assertEqual(kinds(evs), ["sub_in", "sub_out"])
        self.assertEqual(evs[0].player_name, "LeBron James")
        self.assertEqual(evs[0].secondary_player, "Rui Hachimura")

    def test_free_throw_and_block(self):
        ft = parse("Stephen Curry makes free throw 1 of 2", scoringPlay=True, score_value=1)
        self.assertEqual(kinds(ft), ["score"])
        self.assertEqual(ft[0].score_value, 1)
        blk = parse("Anthony Davis blocks Klay Thompson's driving layup")
        self.assertEqual(kinds(blk), ["block"])
        self.assertEqual(blk[0].player_name, "Anthony Davis")

    def test_rebound_and_noise_ignored(self):
        rb = parse("Draymond Green defensive rebound")
        self.assertEqual(kinds(rb), ["rebound"])
        self.assertEqual(parse("Hawks offensive team rebound"), [])
        self.assertEqual(parse("Jump Ball LeBron James vs. Anthony Davis"), [])
        self.assertEqual(parse("Start of 2nd Quarter"), [])

    def test_nba_cdn_format(self):
        evs = parse("Curry 25' 3PT Jump Shot (14 PTS) (Green 3 AST)",
                    scoringPlay=True, score_value=3)
        self.assertIn("score", kinds(evs))
        self.assertIn("assist", kinds(evs))

    def test_roster_resolution(self):
        self.assertEqual(ROSTER.lookup("James").name, "LeBron James")
        self.assertEqual(ROSTER.by_jersey("30")[0].name, "Stephen Curry")
        hits = ROSTER.match_text("James makes shot (Curry assists)")
        self.assertEqual({h.entry.name for h in hits},
                         {"LeBron James", "Stephen Curry"})


if __name__ == "__main__":
    unittest.main()
