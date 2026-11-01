"""接口冒烟测试：不依赖第三方库，起一个临时端口跑完整链路。

    python tests/smoke_test.py

覆盖：健康检查 → 新建作品 → 保存设定 → 流式大纲 → 流式正文 → 导出 → 删除
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novelgen.server import Handler  # noqa: E402
from novelgen import store  # noqa: E402

BASE = ""


def request(method: str, path: str, payload=None) -> tuple[int, bytes]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def stream(path: str, payload=None) -> list[dict]:
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    messages = []
    with urllib.request.urlopen(req, timeout=60) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            messages.append(json.loads(chunk))
    return messages


def main() -> int:
    global BASE
    try:  # Windows 控制台默认 GBK，避免打印时炸掉
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    store.ensure_dirs()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    BASE = f"http://127.0.0.1:{port}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[1/6] 服务已启动 {BASE}")

    failures = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"      {mark}  {name}" + (f"  ({detail})" if detail and not condition else ""))
        if not condition:
            failures.append(name)

    status, body = request("GET", "/api/health")
    check("健康检查", status == 200 and json.loads(body)["ok"] is True)

    status, body = request("POST", "/api/projects", {"title": "雨夜归人"})
    project = json.loads(body)
    check("新建作品", status == 201 and project["title"] == "雨夜归人")
    pid = project["id"]

    setup = {
        "genre": "悬疑",
        "style": "冷峻克制",
        "premise": "一个失忆的男人在雨夜找回了自己的名字",
        "protagonist": "林砚，32 岁，前刑警",
        "world": "南方小城，连下了半个月的雨",
    }
    status, body = request("PATCH", f"/api/projects/{pid}", {"setup": setup})
    check("保存设定", status == 200 and json.loads(body)["setup"]["genre"] == "悬疑")

    events = stream(f"/api/projects/{pid}/outline")
    delta_len = sum(len(e.get("delta", "")) for e in events)
    outline_event = next((e for e in events if e.get("event") == "outline"), None)
    check("流式大纲", delta_len > 50 and outline_event is not None, f"收到 {delta_len} 字")
    if outline_event:
        chapters = outline_event["project"]["outline"]
        check("大纲至少 8 章", len(chapters) >= 8, f"实际 {len(chapters)} 章")

    events = stream(f"/api/projects/{pid}/chapters/0/write", {"mode": "write"})
    saved = next((e for e in events if e.get("event") == "saved"), None)
    check("流式正文", saved is not None and saved["word_count"] > 100,
          f"字数 {saved['word_count'] if saved else 0}")

    status, body = request("GET", f"/api/projects/{pid}/export?format=md")
    check("导出 Markdown", status == 200 and body.decode("utf-8").startswith("# 雨夜归人"))

    status, _ = request("DELETE", f"/api/projects/{pid}")
    check("删除作品", status == 200)

    httpd.shutdown()

    print()
    if failures:
        print(f"FAILED: {len(failures)} 项未通过 -> {', '.join(failures)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
