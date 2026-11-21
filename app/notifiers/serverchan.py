"""Server酱（微信）推送，作为企业微信的补充通道。"""
from __future__ import annotations

import requests

from ..models import Alert
from .base import Notifier


class ServerChanNotifier(Notifier):
    name = "serverchan"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.key = str(cfg.get("notify.serverchan.key", "") or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def send(self, alert: Alert) -> str:
        e = alert.event
        desp = "\n\n".join([
            alert.body,
            f"- 比赛：Q{e.period} {e.clock}" if e.period else "",
            f"- 比分：{e.away_score} - {e.home_score}",
            f"- 来源：{'画面 OCR' if e.source == 'vision' else '实时数据'}",
        ])
        try:
            r = requests.post(f"https://sctapi.ftqq.com/{self.key}.send",
                              data={"title": alert.title, "desp": desp}, timeout=10)
            data = r.json() if r.content else {}
            if data.get("code") not in (0, None):
                return f"error: {data.get('message', data)}"
            return "ok"
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}: {exc}"
