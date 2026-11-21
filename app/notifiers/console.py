"""控制台通道：调试用，始终可用。"""
from __future__ import annotations

import logging

from ..models import Alert
from .base import Notifier

log = logging.getLogger(__name__)


class ConsoleNotifier(Notifier):
    name = "console"

    def send(self, alert: Alert) -> str:
        log.info("[ALERT] %s | %s", alert.title, alert.event.text[:80])
        return "ok"
