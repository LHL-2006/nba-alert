"""企业微信群机器人推送。"""
from __future__ import annotations

import requests

from ..models import Alert
from .base import Notifier


class WeComNotifier(Notifier):
    name = "wecom"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.webhook = str(cfg.get("notify.wecom.webhook", "") or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.webhook)

    def send(self, alert: Alert) -> str:
        e = alert.event
        lines = [
            f"### {alert.title}",
            f"> **比赛**：Q{e.period} {e.clock}" if e.period else f"> {alert.title}",
            f"> **比分**：{e.away_score} - {e.home_score}",
            f"> **详情**：{e.text}",
            f"> **来源**：{'画面 OCR' if e.source == 'vision' else '实时数据'}",
        ]
        payload = {"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}}
        try:
            r = requests.post(self.webhook, json=payload, timeout=10)
            data = r.json() if r.content else {}
            if data.get("errcode", 0) != 0:
                return f"error: {data.get('errmsg', data)}"
            return "ok"
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}: {exc}"
