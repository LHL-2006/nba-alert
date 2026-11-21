"""NBA 关注球员实时提醒 —— Windows 桌面应用入口。

打包后双击 NBAAlert.exe 即可使用，不需要 WorkBuddy、不需要命令行：
  * 后台内嵌启动 FastAPI / WebSocket 服务
  * 自动打开默认浏览器到实时面板
  * 常驻系统托盘（打开面板 / 演示模式 / 重启 / 查看日志 / 退出）
  * config.yaml 与 .env 位于 exe 同目录，首次运行自动释放，可直接编辑
"""
from __future__ import annotations

import io
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()
BUNDLE = Path(getattr(sys, "_MEIPASS", str(APP_DIR)))
sys.path.insert(0, str(BUNDLE))
sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)
os.environ.setdefault("NBA_ALERT_HOME", str(APP_DIR))

# --windowed 打包后 stdout/stderr 可能为 None，避免第三方库 print 时报错
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

(APP_DIR / "data").mkdir(exist_ok=True)


def _seed(name: str) -> None:
    target = APP_DIR / name
    if target.exists():
        return
    src = BUNDLE / name
    if src.exists():
        target.write_bytes(src.read_bytes())


_seed("config.yaml")
_seed(".env.example")

logging.basicConfig(
    filename=str(APP_DIR / "data" / "app.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("launcher")

PORT = 8000
URL = f"http://127.0.0.1:{PORT}"
LOCK_PORT = 8765
_lock_socket: socket.socket | None = None


def _single_instance() -> bool:
    """用独立端口做单实例锁；已运行时直接打开面板并退出。"""
    global _lock_socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        _lock_socket = s
        return True
    except OSError:
        s.close()
        return False


def _wait_port(timeout: float = 25.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


class DesktopApp:
    def __init__(self):
        from app.config import Config
        self.cfg_path = APP_DIR / "config.yaml"
        self.cfg = Config.load(str(self.cfg_path))
        self.demo = bool(self.cfg.get("app.demo_mode", False))
        self.server = None
        self.thread: threading.Thread | None = None
        self.icon = None

    def start_server(self) -> None:
        import uvicorn
        from app.config import Config
        from app.server import create_app

        cfg = Config.load(str(self.cfg_path))
        cfg.set("app.demo_mode", self.demo)
        application = create_app(cfg)
        ucfg = uvicorn.Config(application, host="127.0.0.1", port=PORT,
                              log_level="warning", access_log=False)
        srv = uvicorn.Server(ucfg)
        # uvicorn 在子线程里不安装信号处理器
        srv.install_signal_handlers = lambda: None
        self.server = srv
        self.thread = threading.Thread(target=srv.run, daemon=True, name="uvicorn")
        self.thread.start()
        log.info("服务已启动 demo=%s", self.demo)

    def _open_browser(self) -> None:
        if _wait_port():
            webbrowser.open(URL)
            log.info("已打开面板 %s", URL)
        else:
            log.error("服务未在预期时间内就绪，请查看日志")

    def restart(self) -> None:
        if self.server:
            self.server.should_exit = True
            for _ in range(40):
                if self.thread and not self.thread.is_alive():
                    break
                time.sleep(0.2)
        self.start_server()
        self._open_browser()

    def open_panel(self, *_) -> None:
        webbrowser.open(URL)

    def toggle_demo(self, *_) -> None:
        self.demo = not self.demo
        log.info("切换演示模式 -> %s", self.demo)
        threading.Thread(target=self.restart, daemon=True).start()

    def restart_async(self, *_) -> None:
        threading.Thread(target=self.restart, daemon=True).start()

    def open_folder(self, *_) -> None:
        try:
            os.startfile(str(APP_DIR))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            log.warning("打开目录失败: %s", exc)

    def open_log(self, *_) -> None:
        p = APP_DIR / "data" / "app.log"
        try:
            os.startfile(str(p))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            log.warning("打开日志失败: %s", exc)

    def quit(self, *_) -> None:
        log.info("应用退出")
        if self.server:
            self.server.should_exit = True
        if self.icon:
            self.icon.stop()

    @staticmethod
    def _make_icon():
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((3, 3, 61, 61), fill=(255, 106, 61, 255),
                  outline=(255, 255, 255, 255), width=3)
        d.line((3, 32, 61, 32), fill=(255, 255, 255, 230), width=3)
        d.line((32, 3, 32, 61), fill=(255, 255, 255, 230), width=3)
        d.arc((9, 3, 55, 61), 55, 305, fill=(255, 255, 255, 230), width=3)
        d.arc((9, 3, 55, 61), 235, 125, fill=(255, 255, 255, 230), width=3)
        return im

    def run(self) -> None:
        import pystray
        from pystray import MenuItem as Item

        self.start_server()
        threading.Thread(target=self._open_browser, daemon=True).start()

        menu = pystray.Menu(
            Item("打开实时面板", self.open_panel, default=True),
            Item("演示模式（回放样本）", self.toggle_demo,
                 checked=lambda icon: self.demo),
            Item("重启服务", self.restart_async),
            pystray.Menu.SEPARATOR,
            Item("打开应用目录", self.open_folder),
            Item("查看运行日志", self.open_log),
            pystray.Menu.SEPARATOR,
            Item("退出", self.quit),
        )
        self.icon = pystray.Icon("nba_alert", self._make_icon(),
                                 f"NBA 关注球员提醒 · {URL}", menu)
        self.icon.run()


def main() -> None:
    if not _single_instance():
        webbrowser.open(URL)   # 已在运行：直接打开面板
        return
    try:
        DesktopApp().run()
    except Exception as exc:  # noqa: BLE001
        log.exception("应用启动失败: %s", exc)
        raise


if __name__ == "__main__":
    main()
