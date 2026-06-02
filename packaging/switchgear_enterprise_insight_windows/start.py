"""Start the switchgear enterprise insight web app with plain Python.

Usage:
    python start.py
    python start.py --port 8791
    python start.py --lan
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from threading import Timer
import webbrowser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动施耐德盘厂企业洞察研究工作台。")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8790, help="监听端口，默认 8790")
    parser.add_argument("--lan", action="store_true", help="局域网共享模式，监听 0.0.0.0")
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 9):
        print("需要 Python 3.9 或更高版本。")
        return 1

    project_dir = Path(__file__).resolve().parent
    src_dir = project_dir / "src"
    if src_dir.exists():
        sys.path.insert(0, str(src_dir))

    host = "0.0.0.0" if args.lan else args.host
    browser_url = f"http://127.0.0.1:{args.port}/"

    try:
        from switchgear_customer_insight.webapp import run_web_app
    except ModuleNotFoundError as exc:
        print("未找到项目模块，请确认 start.py 位于项目根目录，且 src 文件夹存在。")
        print(f"错误信息: {exc}")
        return 1

    print("正在启动施耐德盘厂企业洞察研究工作台...")
    print(f"本机访问: {browser_url}")
    if args.lan:
        print(f"局域网访问: http://本机IP:{args.port}/")
        print("如 Windows 防火墙提示，请允许 Python 访问网络。")

    if not args.no_browser:
        Timer(0.8, lambda: webbrowser.open(browser_url)).start()

    try:
        run_web_app(host=host, port=args.port)
    except OSError as exc:
        print(f"启动失败：{exc}")
        print("如果端口被占用，可以改用：python start.py --port 8791")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
