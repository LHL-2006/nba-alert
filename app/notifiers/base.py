"""推送适配器抽象与构造。send() 返回 'ok' 或 'error: ...' 字符串，便于面板展示。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Config
from ..models import Alert


class Notifier(ABC):
    name = "base"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    @property
    def enabled(self) -> bool:
        return True

    @abstractmethod
    def send(self, alert: Alert) -> str:
        ...


def build_notifiers(cfg: Config) -> list[Notifier]:
    from .console import ConsoleNotifier
    from .desktop import DesktopNotifier
    from .email import EmailNotifier
    from .serverchan import ServerChanNotifier
    from .wecom import WeComNotifier

    registry: dict[str, type[Notifier]] = {
        "console": ConsoleNotifier,
        "wecom": WeComNotifier,
        "serverchan": ServerChanNotifier,
        "desktop": DesktopNotifier,
        "email": EmailNotifier,
    }
    channels = list(cfg.get("notify.channels", []) or [])
    # 用户配置了 Server酱 key 时自动补上微信通道
    if cfg.get("notify.serverchan.key") and "serverchan" not in channels:
        channels.append("serverchan")

    out: list[Notifier] = []
    for ch in channels:
        cls = registry.get(str(ch).lower())
        if not cls:
            continue
        try:
            n = cls(cfg)
            if n.enabled:
                out.append(n)
        except Exception:  # noqa: BLE001
            continue
    return out
