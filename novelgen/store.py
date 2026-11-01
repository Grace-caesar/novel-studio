"""本地存储层。

所有数据都以 JSON 文件形式存放在 data/ 目录下：
    data/settings.json          模型设置（含 API Key，已被 .gitignore 排除）
    data/projects/<id>.json     单个作品（设定 + 大纲 + 章节）

选择文件存储而不是数据库，是为了让项目零依赖、拷走即可用；
写入采用「临时文件 + 原子替换」，避免写到一半崩溃导致文件损坏。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "temperature": 0.9,
    "max_tokens": 4096,
    "chapter_words": 2500,
    "outline_chapters": 12,
}

DEFAULT_SETUP = {
    "genre": "玄幻",
    "style": "轻松幽默",
    "pov": "第三人称",
    "premise": "",
    "world": "",
    "protagonist": "",
    "extra": "",
}


# --------------------------------------------------------------------------- #
# 基础读写
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# 文本工具
# --------------------------------------------------------------------------- #
_WS = re.compile(r"\s+")


def count_words(text: str) -> int:
    """中文按字符、英文按词计数的简化字数统计。"""
    if not text:
        return 0
    compact = _WS.sub("", text)
    return len(compact)


# --------------------------------------------------------------------------- #
# 设置
# --------------------------------------------------------------------------- #
def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    settings.update(read_json(SETTINGS_FILE, {}) or {})
    return settings


def save_settings(patch: dict) -> dict:
    settings = load_settings()
    for key in DEFAULT_SETTINGS:
        if key in patch and patch[key] not in (None, ""):
            settings[key] = patch[key]
    # api_key 允许被显式清空
    if "api_key" in patch and patch["api_key"] == "":
        settings["api_key"] = ""
    write_json(SETTINGS_FILE, settings)
    return settings


def public_settings() -> dict:
    """给前端用的设置：不返回明文 Key，只告诉它有没有配。"""
    settings = load_settings()
    safe = dict(settings)
    safe["api_key"] = ""
    safe["has_key"] = bool(settings.get("api_key"))
    return safe


# --------------------------------------------------------------------------- #
# 作品
# --------------------------------------------------------------------------- #
def _project_path(project_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{8,32}", project_id or ""):
        raise ValueError("非法的作品 id")
    return PROJECTS_DIR / f"{project_id}.json"


def new_project(title: str = "未命名小说") -> dict:
    now = _now()
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title.strip() or "未命名小说",
        "created_at": now,
        "updated_at": now,
        "setup": dict(DEFAULT_SETUP),
        "outline": [],
        "chapters": [],
    }


def list_projects() -> list[dict]:
    ensure_dirs()
    items = []
    for path in PROJECTS_DIR.glob("*.json"):
        project = read_json(path, None)
        if not isinstance(project, dict) or "id" not in project:
            continue
        chapters = project.get("chapters") or []
        items.append(
            {
                "id": project["id"],
                "title": project.get("title") or "未命名小说",
                "updated_at": project.get("updated_at", ""),
                "chapter_count": len(chapters),
                "word_count": sum(count_words(c.get("content", "")) for c in chapters),
            }
        )
    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return items


def load_project(project_id: str) -> dict:
    project = read_json(_project_path(project_id), None)
    if not isinstance(project, dict):
        raise KeyError("作品不存在")
    project.setdefault("setup", dict(DEFAULT_SETUP))
    project.setdefault("outline", [])
    project.setdefault("chapters", [])
    return project


def save_project(project: dict) -> dict:
    project["updated_at"] = _now()
    write_json(_project_path(project["id"]), project)
    return project


def delete_project(project_id: str) -> None:
    path = _project_path(project_id)
    if not path.exists():
        raise KeyError("作品不存在")
    path.unlink()


def create_project(title: str) -> dict:
    ensure_dirs()
    project = new_project(title)
    return save_project(project)


def project_summary(project: dict) -> dict:
    return {
        "id": project["id"],
        "title": project.get("title", "未命名小说"),
        "updated_at": project.get("updated_at", ""),
        "chapter_count": len(project.get("chapters") or []),
        "word_count": sum(count_words(c.get("content", "")) for c in project.get("chapters") or []),
    }


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
def export_markdown(project: dict) -> str:
    setup = project.get("setup") or {}
    lines = [f"# {project.get('title', '未命名小说')}", ""]
    meta = "  ".join(
        part
        for part in (
            f"题材：{setup.get('genre')}" if setup.get("genre") else "",
            f"风格：{setup.get('style')}" if setup.get("style") else "",
            f"视角：{setup.get('pov')}" if setup.get("pov") else "",
        )
        if part
    )
    if meta:
        lines += [f"> {meta}", ""]
    if setup.get("premise"):
        lines += ["## 故事梗概", "", setup["premise"], ""]
    for index, chapter in enumerate(project.get("chapters") or [], start=1):
        title = chapter.get("title") or f"第 {index} 章"
        lines += [f"## {title}", "", (chapter.get("content") or "").strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def export_txt(project: dict) -> str:
    lines = [project.get("title", "未命名小说"), ""]
    for index, chapter in enumerate(project.get("chapters") or [], start=1):
        title = chapter.get("title") or f"第 {index} 章"
        lines += [title, "", (chapter.get("content") or "").strip(), ""]
    return "\n".join(lines).rstrip() + "\n"
