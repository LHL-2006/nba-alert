"""SMTP 邮件推送（默认 465 SSL，587 自动 STARTTLS）。"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from ..models import Alert
from .base import Notifier


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.host = str(cfg.get("notify.email.host", "smtp.qq.com") or "")
        self.port = int(cfg.get("notify.email.port", 465) or 465)
        self.user = str(cfg.get("notify.email.user", "") or "").strip()
        self.password = str(cfg.get("notify.email.password", "") or "")
        self.to = [str(x) for x in (cfg.get("notify.email.to", []) or []) if x]
        self.prefix = str(cfg.get("notify.email.subject_prefix", "[NBA 提醒]"))

    @property
    def enabled(self) -> bool:
        return (bool(self.cfg.get("notify.email.enabled", True))
                and bool(self.user and self.password and self.to))

    def send(self, alert: Alert) -> str:
        e = alert.event
        msg = EmailMessage()
        msg["Subject"] = f"{self.prefix} {alert.title}"
        msg["From"] = self.user
        msg["To"] = ", ".join(self.to)
        body = "\n".join([
            alert.body,
            "",
            f"回合详情：{e.text}",
            f"数据源：{e.source}",
            f"置信度：{e.confidence:.2f}",
        ])
        msg.set_content(body, charset="utf-8")
        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=10) as s:
                    s.login(self.user, self.password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=10) as s:
                    s.starttls()
                    s.login(self.user, self.password)
                    s.send_message(msg)
            return "ok"
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}: {exc}"
