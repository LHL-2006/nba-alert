"""配置加载：YAML + ${ENV_VAR} 展开 + 默认值深合并。"""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

DEFAULT_CONFIG: dict[str, Any] = {
    "app": {
        "demo_mode": False,
        "poll_interval_sec": 8,
        "date": None,
        "host": "127.0.0.1",
        "port": 8000,
    },
    "data_source": {
        "prefer": "auto",
        "timeout_sec": 15,
        "fail_threshold": 2,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    },
    "watch": {
        "default_events": ["on_court", "sub_in", "sub_out", "score", "assist", "turnover"],
        "cooldown_sec": 0,
        "players": [],
    },
    "vision": {
        "enabled": True,
        "stream_url": "",
        "grabber": "auto",
        "fps": 0.5,
        "roi": None,
        "ocr_backend": "rapidocr",
        "min_score": 0.55,
        "vote_window": 6,
        "vote_threshold": 3,
        "absent_frames": 8,
        "jersey_mode": True,
        "text_mode": True,
    },
    "notify": {
        "channels": ["console"],
        "wecom": {"webhook": ""},
        "serverchan": {"key": ""},
        "desktop": {"enabled": True, "duration_sec": 8},
        "email": {
            "enabled": True, "host": "smtp.qq.com", "port": 465,
            "user": "", "password": "", "to": [], "subject_prefix": "[NBA 提醒]",
        },
    },
}


def _expand_env(obj: Any) -> Any:
    if isinstance(obj, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_dotenv(path: Path) -> None:
    """极简 .env 读取，不引入 python-dotenv 依赖。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


class Config:
    def __init__(self, raw: dict[str, Any], path: str = ""):
        self.raw = raw
        self.path = path

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        cfg_path = Path(path or os.environ.get("NBA_ALERT_CONFIG", "config.yaml"))
        if not cfg_path.is_absolute():
            cfg_path = (Path.cwd() / cfg_path).resolve()
        _load_dotenv(cfg_path.parent / ".env")
        raw: dict[str, Any] = {}
        if cfg_path.exists():
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"配置文件根节点必须是映射: {cfg_path}")
            raw = loaded
        return cls(_expand_env(_deep_merge(DEFAULT_CONFIG, raw)), str(cfg_path))

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur if cur is not None else default

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        cur = self.raw
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    @property
    def watch_players(self) -> list[dict[str, Any]]:
        return self.get("watch.players", []) or []

    @property
    def default_events(self) -> list[str]:
        return self.get("watch.default_events", []) or []

    def events_for(self, player: dict[str, Any]) -> set[str]:
        return set(player.get("events") or self.default_events)
