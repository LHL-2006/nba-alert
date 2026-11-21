"""重新打包 Windows 桌面应用：python build_app.py

产物：dist/NBAAlert/NBAAlert.exe（绿色免安装，双击即用）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

COLLECT = (
    "cv2", "onnxruntime", "rapidocr_onnxruntime", "numpy",
    "nba_api", "pystray", "PIL",
)
HIDDEN = (
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "nba_api.live.nba.endpoints.scoreboard",
    "nba_api.live.nba.endpoints.boxscore",
    "app.config", "app.server", "app.runtime", "app.engine", "app.state",
)
DATA = (("web", "web"), ("config.yaml", "."), (".env.example", "."))


def main() -> int:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "NBAAlert",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT),
    ]
    for pkg in COLLECT:
        cmd += ["--collect-all", pkg]
    for src, dst in DATA:
        cmd += ["--add-data", f"{ROOT / src};{dst}"]
    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]
    cmd.append(str(ROOT / "launcher.py"))

    print("打包命令：\n" + " ".join(cmd) + "\n")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("打包失败，请检查上面的日志")
        return result.returncode
    exe = ROOT / "dist" / "NBAAlert" / "NBAAlert.exe"
    print(f"\n完成：{exe}")
    print("把整个 dist/NBAAlert 文件夹复制到任意位置即可使用；")
    print("配置 config.yaml 与 .env 位于 exe 同目录，首次运行会自动释放。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
