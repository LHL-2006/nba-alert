"""Windows 原生桌面气泡通知（无需额外 Python 包）。"""
from __future__ import annotations

import os
import subprocess
import sys

from ..models import Alert
from .base import Notifier

_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.BalloonTipTitle = $env:NBA_TITLE
$n.BalloonTipText = $env:NBA_BODY
$n.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
$n.Visible = $true
$n.ShowBalloonTip(8000)
Start-Sleep -Seconds 8
$n.Visible = $false
$n.Dispose()
"""


class DesktopNotifier(Notifier):
    name = "desktop"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.duration = int(cfg.get("notify.desktop.duration_sec", 8) or 8)

    @property
    def enabled(self) -> bool:
        return sys.platform == "win32" and bool(self.cfg.get("notify.desktop.enabled", True))

    def send(self, alert: Alert) -> str:
        env = dict(os.environ)
        env["NBA_TITLE"] = alert.title[:200]
        env["NBA_BODY"] = (alert.body[:400] + "\n" + alert.event.text[:200])
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return "ok (async)"
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}: {exc}"
