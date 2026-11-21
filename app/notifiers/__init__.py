"""推送适配层。"""
from .base import Notifier, build_notifiers
from .console import ConsoleNotifier
from .desktop import DesktopNotifier
from .email import EmailNotifier
from .serverchan import ServerChanNotifier
from .wecom import WeComNotifier

__all__ = [
    "Notifier", "build_notifiers", "ConsoleNotifier", "DesktopNotifier",
    "EmailNotifier", "ServerChanNotifier", "WeComNotifier",
]
