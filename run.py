"""启动入口：python run.py  （或 uvicorn run:app --reload）"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.server import create_app  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)

cfg = Config.load(str(ROOT / "config.yaml"))
# 便捷开关：python run.py --demo 立即用内置样本回放验证全链路
if "--demo" in sys.argv:
    cfg.set("app.demo_mode", True)
    cfg.set("app.poll_interval_sec", 2)
    cfg.set("notify.channels", ["console"])
    print("[demo] 演示模式已启用：不访问网络，2 秒一拍，推送仅走控制台")
app = create_app(cfg)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=str(cfg.get("app.host", "127.0.0.1")),
        port=int(cfg.get("app.port", 8000)),
        log_level="info",
    )
