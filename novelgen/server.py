"""HTTP 服务：静态页面 + REST API + SSE 流式生成。

路由一览
--------
GET    /api/health
GET    /api/settings                读模型设置（不回传 Key 明文）
PUT    /api/settings                保存模型设置
GET    /api/projects                作品列表
POST   /api/projects                新建作品
GET    /api/projects/<id>           作品详情
PATCH  /api/projects/<id>           修改标题 / 设定 / 大纲
DELETE /api/projects/<id>           删除作品
POST   /api/projects/<id>/outline   SSE 生成大纲
POST   /api/projects/<id>/chapters  新增空章节
PUT    /api/projects/<id>/chapters/<i>   保存章节
DELETE /api/projects/<id>/chapters/<i>   删除章节
POST   /api/projects/<id>/chapters/<i>/write  SSE 生成/续写/重写正文
GET    /api/projects/<id>/export?format=md|txt  导出
"""

from __future__ import annotations

import json
import mimetypes
import re
import sys
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, demo, llm, prompts, store

WEB_DIR = (store.ROOT_DIR / "web").resolve()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_outline(text: str, want: int) -> list[dict]:
    """从模型输出里尽力解析出章节大纲。

    先按 JSON 解析，失败再退化成按行匹配「1. 标题：要点」。
    """
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()

    start, end = raw.find("["), raw.rfind("]")
    candidates = []
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data = data.get("chapters") or data.get("outline") or []
        if not isinstance(data, list):
            continue
        chapters = []
        for item in data:
            if isinstance(item, str):
                chapters.append({"title": item.strip(), "summary": ""})
            elif isinstance(item, dict):
                title = str(item.get("title") or item.get("name") or "").strip()
                summary = str(item.get("summary") or item.get("plot") or "").strip()
                if title or summary:
                    chapters.append({"title": title or f"第 {len(chapters) + 1} 章", "summary": summary})
        if chapters:
            return chapters[: max(1, want)]

    fallback = []
    for line in raw.splitlines():
        match = re.match(r"^\s*(?:第?\s*)?(\d{1,3})[.、)章]?\s*[：:、.\-]?\s*(.+)$", line)
        if not match:
            continue
        rest = match.group(2).strip()
        if not rest:
            continue
        title, _, summary = rest.partition("：")
        fallback.append({"title": (title or rest)[:20], "summary": summary.strip()})
    return fallback[: max(1, want)]


class Handler(BaseHTTPRequestHandler):
    server_version = f"NovelStudio/{__version__}"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- 基础工具
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Windows 命令行里用 curl 传中文时可能是 GBK，顺手兼容一下
            try:
                text = raw.decode("gbk")
            except UnicodeDecodeError:
                raise ValueError("请求体不是合法 JSON") from None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError("请求体不是合法 JSON") from None
        return data if isinstance(data, dict) else {}

    # ---------------------------------------------------------------- SSE
    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse_send(self, payload) -> bool:
        try:
            data = json.dumps(payload, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _sse_done(self) -> None:
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            pass

    # ---------------------------------------------------------------- 入口
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        try:
            if parts and parts[0] == "api":
                self._api(method, parts[1:], query)
            elif method == "GET":
                self._static(parts)
            else:
                self._error(405, "不支持的请求方法")
        except KeyError as exc:
            self._error(404, str(exc).strip("'\"") or "资源不存在")
        except ValueError as exc:
            self._error(400, str(exc))
        except llm.LLMError as exc:
            self._error(502, str(exc))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - 兜底，避免线程直接崩掉
            sys.stderr.write(f"未处理异常: {exc!r}\n")
            try:
                self._error(500, f"服务器内部错误：{exc}")
            except OSError:
                pass

    # ---------------------------------------------------------------- 静态文件
    def _static(self, parts: list[str]) -> None:
        relative = "/".join(parts) or "index.html"
        target = (WEB_DIR / relative).resolve()
        if WEB_DIR not in target.parents and target != WEB_DIR:
            self._error(403, "越界访问")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._error(404, "文件不存在")
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ---------------------------------------------------------------- API
    def _api(self, method: str, parts: list[str], query: dict) -> None:
        if not parts:
            self._error(404, "未知接口")
            return

        head = parts[0]

        if head == "health":
            self._send_json(200, {"ok": True, "version": __version__})
            return

        if head == "settings":
            if method == "GET":
                self._send_json(200, store.public_settings())
            elif method in ("PUT", "POST"):
                body = self._read_body()
                store.save_settings(body)
                self._send_json(200, store.public_settings())
            else:
                self._error(405, "不支持的请求方法")
            return

        if head != "projects":
            self._error(404, "未知接口")
            return

        # /api/projects
        if len(parts) == 1:
            if method == "GET":
                self._send_json(200, {"projects": store.list_projects()})
            elif method == "POST":
                body = self._read_body()
                project = store.create_project(str(body.get("title") or "未命名小说"))
                self._send_json(201, project)
            else:
                self._error(405, "不支持的请求方法")
            return

        project_id = parts[1]
        rest = parts[2:]

        # /api/projects/<id>
        if not rest:
            if method == "GET":
                self._send_json(200, store.load_project(project_id))
            elif method == "DELETE":
                store.delete_project(project_id)
                self._send_json(200, {"ok": True})
            elif method in ("PATCH", "PUT"):
                self._update_project(project_id, self._read_body())
            else:
                self._error(405, "不支持的请求方法")
            return

        # /api/projects/<id>/export
        if rest == ["export"]:
            fmt = (query.get("format") or ["md"])[0]
            project = store.load_project(project_id)
            if fmt == "txt":
                text = store.export_txt(project)
                ctype, ext = "text/plain; charset=utf-8", "txt"
            else:
                text = store.export_markdown(project)
                ctype, ext = "text/markdown; charset=utf-8", "md"
            body = text.encode("utf-8")
            filename = f"{project.get('title', 'novel')}.{ext}"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{_quote(filename)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # /api/projects/<id>/outline
        if rest == ["outline"]:
            if method != "POST":
                self._error(405, "不支持的请求方法")
                return
            self._stream_outline(project_id)
            return

        # /api/projects/<id>/chapters
        if rest[0] == "chapters":
            self._chapters(method, project_id, rest[1:])
            return

        self._error(404, "未知接口")

    def _chapters(self, method: str, project_id: str, rest: list[str]) -> None:
        project = store.load_project(project_id)
        chapters = project.setdefault("chapters", [])

        if not rest:
            if method == "POST":
                body = self._read_body()
                chapters.append(
                    {
                        "id": uuid.uuid4().hex[:8],
                        "title": str(body.get("title") or f"第 {len(chapters) + 1} 章"),
                        "content": "",
                        "updated_at": _now(),
                    }
                )
                store.save_project(project)
                self._send_json(201, project)
            else:
                self._error(405, "不支持的请求方法")
            return

        try:
            index = int(rest[0])
        except ValueError:
            self._error(400, "章节序号必须是数字")
            return
        if index < 0 or index >= len(chapters):
            self._error(404, "章节不存在")
            return

        sub = rest[1:]

        if not sub:
            if method in ("PUT", "PATCH"):
                body = self._read_body()
                if "title" in body:
                    chapters[index]["title"] = str(body["title"])
                if "content" in body:
                    chapters[index]["content"] = str(body["content"])
                chapters[index]["updated_at"] = _now()
                store.save_project(project)
                self._send_json(200, {"ok": True, "chapter": chapters[index]})
            elif method == "DELETE":
                chapters.pop(index)
                store.save_project(project)
                self._send_json(200, {"ok": True})
            else:
                self._error(405, "不支持的请求方法")
            return

        if sub == ["write"]:
            if method != "POST":
                self._error(405, "不支持的请求方法")
                return
            body = self._read_body()
            mode = body.get("mode") or "write"
            if mode not in ("write", "continue", "rewrite"):
                mode = "write"
            self._stream_chapter(project_id, index, mode)
            return

        self._error(404, "未知接口")

    # ---------------------------------------------------------------- 业务
    def _update_project(self, project_id: str, body: dict) -> None:
        project = store.load_project(project_id)
        if "title" in body:
            project["title"] = str(body["title"]).strip() or project["title"]
        if isinstance(body.get("setup"), dict):
            project.setdefault("setup", {}).update(body["setup"])
        if isinstance(body.get("outline"), list):
            new_outline = []
            for item in body["outline"]:
                if isinstance(item, dict):
                    new_outline.append(
                        {
                            "title": str(item.get("title") or "").strip(),
                            "summary": str(item.get("summary") or "").strip(),
                        }
                    )
            project["outline"] = new_outline
        store.save_project(project)
        self._send_json(200, project)

    def _stream_outline(self, project_id: str) -> None:
        project = store.load_project(project_id)
        settings = store.load_settings()
        try:
            count = int(settings.get("outline_chapters") or 12)
        except (TypeError, ValueError):
            count = 12
        count = max(1, min(count, 40))

        live = bool(settings.get("api_key"))
        self._sse_start()
        if not self._sse_send({"event": "start", "mode": "live" if live else "demo"}):
            return

        buffer: list[str] = []
        try:
            if live:
                source = llm.stream_chat(settings, prompts.outline_messages(project, count))
            else:
                text = json.dumps(demo.demo_outline(project, count), ensure_ascii=False, indent=2)
                source = _slow_slice(text)

            for piece in source:
                buffer.append(piece)
                if not self._sse_send({"delta": piece}):
                    return

            chapters = parse_outline("".join(buffer), count)
            if not chapters:
                self._sse_send({"event": "error", "message": "没能解析出章节大纲，请重试一次"})
                return

            project["outline"] = chapters
            chapters_meta = project.setdefault("chapters", [])
            while len(chapters_meta) < len(chapters):
                chapters_meta.append(
                    {"id": uuid.uuid4().hex[:8], "title": "", "content": "", "updated_at": _now()}
                )
            for i, item in enumerate(chapters):
                chapter = chapters_meta[i]
                if not (chapter.get("content") or "").strip():
                    chapter["title"] = item["title"]
            store.save_project(project)
            self._sse_send({"event": "outline", "project": project})
        except llm.LLMError as exc:
            self._sse_send({"event": "error", "message": str(exc)})
        finally:
            self._sse_done()

    def _stream_chapter(self, project_id: str, index: int, mode: str) -> None:
        project = store.load_project(project_id)
        settings = store.load_settings()
        chapters = project.setdefault("chapters", [])
        chapter = chapters[index]
        try:
            target = int(settings.get("chapter_words") or 2500)
        except (TypeError, ValueError):
            target = 2500

        live = bool(settings.get("api_key"))
        self._sse_start()
        if not self._sse_send({"event": "start", "mode": "live" if live else "demo"}):
            return

        buffer: list[str] = []
        try:
            if live:
                source = llm.stream_chat(
                    settings, prompts.chapter_messages(project, index, target, mode), timeout=300
                )
            else:
                source = demo.demo_chapter(project, index, mode)

            for piece in source:
                buffer.append(piece)
                if not self._sse_send({"delta": piece}):
                    return

            text = "".join(buffer).strip()
            if not text:
                self._sse_send({"event": "error", "message": "模型没有返回内容"})
                return

            if mode == "continue":
                chapter["content"] = ((chapter.get("content") or "").rstrip() + "\n\n" + text).strip()
            else:
                chapter["content"] = text
            chapter["updated_at"] = _now()
            store.save_project(project)
            self._sse_send(
                {
                    "event": "saved",
                    "chapter": chapter,
                    "word_count": store.count_words(chapter["content"]),
                }
            )
        except llm.LLMError as exc:
            self._sse_send({"event": "error", "message": str(exc)})
        finally:
            self._sse_done()


def _slow_slice(text: str, size: int = 12):
    """把整段文本切片输出，模拟打字机效果。"""
    import time

    for i in range(0, len(text), size):
        yield text[i : i + size]
        time.sleep(0.008)


def _quote(name: str) -> str:
    from urllib.parse import quote

    return quote(name, safe="")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    store.ensure_dirs()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    banner = f"""
  墨语 · Novel Studio  v{__version__}
  ─────────────────────────────────────
  打开浏览器访问:  http://{host}:{port}
  数据目录:        {store.DATA_DIR}
  停止服务:        Ctrl + C
"""
    print(banner, flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
