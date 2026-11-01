"""墨语 · Novel Studio 启动入口。

    python app.py            # 默认 http://127.0.0.1:8765
    python app.py --port 9000
"""

import argparse
import sys

from novelgen.server import serve


def main() -> int:
    parser = argparse.ArgumentParser(description="墨语 · Novel Studio — AI 小说生成器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    args = parser.parse_args()

    try:
        serve(args.host, args.port)
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
