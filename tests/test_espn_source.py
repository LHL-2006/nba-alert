"""ESPN 响应解析单元测试（内联 fixture，不访问网络）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sources.espn_source import _game_from_event  # noqa: E402
from app.sources.roster import RosterIndex  # noqa: E402

SCOREBOARD_EVENT = {
    "id": "401909305",
    "competitions": [{
        "status": {"period": 4, "displayClock": "7:12",
                   "type": {"state": "in", "shortDetail": "7:12 - 4th Quarter"}},
        "competitors": [
            {"homeAway": "home", "score": "102",
             "team": {"id": "1", "displayName": "Atlanta Hawks", "abbreviation": "ATL"}},
            {"homeAway": "away", "score": "99",
             "team": {"id": "30", "displayName": "Charlotte Hornets", "abbreviation": "CHA"}},
        ],
    }],
}

SUMMARY = {
    "boxscore": {"players": [{
        "team": {"id": "1", "abbreviation": "ATL"},
        "statistics": [{
            "labels": ["MIN", "PTS"],
            "athletes": [
                {"athlete": {"id": "4433249", "displayName": "Moussa Diabate", "jersey": "14"},
                 "stats": ["22", "8"]},
                {"athlete": {"id": "4433250", "displayName": "Jalen Johnson", "jersey": "1"},
                 "stats": ["30", "20"]},
            ],
        }],
    }]},
    "plays": [
        {"id": "10", "text": "Jalen Johnson makes 1-foot running dunk",
         "period": {"number": 1}, "clock": {"displayValue": "11:23"},
         "scoringPlay": True, "scoreValue": 2, "homeScore": 2, "awayScore": 3,
         "participants": [{"athlete": {"id": "4433250"}}]},
    ],
}


class TestESPNParsing(unittest.TestCase):
    def test_game_from_event(self):
        g = _game_from_event(SCOREBOARD_EVENT)
        self.assertIsNotNone(g)
        self.assertEqual(g.game_id, "espn:401909305")
        self.assertEqual(g.status, "in")
        self.assertEqual(g.home.name, "Atlanta Hawks")
        self.assertEqual((g.home_score, g.away_score), (102, 99))
        self.assertEqual(g.clock, "7:12")

    def test_roster_from_summary(self):
        r = RosterIndex.from_espn(SUMMARY)
        self.assertEqual(len(r), 2)
        self.assertEqual(r.lookup("Jalen Johnson").jersey, "1")
        self.assertEqual(r.by_jersey("14")[0].name, "Moussa Diabate")
        self.assertEqual(r.by_id["4433250"].team_abbrev, "ATL")

    def test_missing_fields_are_tolerated(self):
        self.assertIsNone(_game_from_event({"competitions": []}))
        self.assertEqual(len(RosterIndex.from_espn({})), 0)


if __name__ == "__main__":
    unittest.main()
