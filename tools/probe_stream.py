"""命令行流地址探测。

用法：python tools/probe_stream.py <直播间页面URL>

仅提取页面中明文出现的 m3u8 地址（等价于浏览器 Network 面板可见内容）。
不破解加密、不绕过授权；请确保你对所观看的直播内容拥有合法权限。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.vision.stream import probe_m3u8  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    page = sys.argv[1]
    print(f"探测页面: {page}\n")
    urls = probe_m3u8(page)
    if not urls:
        print("未发现明文 m3u8 地址。常见原因：")
        print("  1. 流地址由 JS 动态生成 / 接口返回，需浏览器 F12 → Network 过滤 .m3u8")
        print("  2. 页面做了 base64 / eval 混淆且非标准包装")
        print("  3. 该站点需要特定 Referer 或 Cookie")
        print("\n拿到地址后填入 config.yaml 的 vision.stream_url 并重启服务。")
        return 2
    for i, u in enumerate(urls, 1):
        print(f"  [{i}] {u}")
    print(f"\n共 {len(urls)} 个。将其中一个填入 config.yaml → vision.stream_url 后重启。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
