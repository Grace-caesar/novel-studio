"""提示词工程。

小说生成的质量，八成取决于提示词怎么组织。这里把「设定 → 大纲 → 正文」
拆成三次调用，每一层都把上层结果作为上下文喂回去，保证长文不跑偏：

    1. 大纲：世界观 + 主角 + 梗概  →  JSON 章节列表
    2. 正文：设定 + 全书大纲 + 前情提要 + 本章大纲 →  本章正文
    3. 续写：已写正文 + 续写指令 →  后续段落
"""

from __future__ import annotations

OUTLINE_SYSTEM = (
    "你是一位资深网文编辑与小说策划，擅长设计节奏紧凑、章末留钩子的章节大纲。"
    "你只输出合法 JSON，不写任何解释、不使用 Markdown 代码块。"
)

WRITER_SYSTEM = (
    "你是一位职业小说作家，文笔细腻、画面感强，擅长用对话和动作推进情节，"
    "避免空洞的形容词堆砌。你只输出小说正文，不输出标题、章节号、说明或注释。"
)


def _setup_block(setup: dict) -> str:
    rows = [
        ("题材", setup.get("genre")),
        ("风格", setup.get("style")),
        ("叙事视角", setup.get("pov")),
        ("一句话梗概", setup.get("premise")),
        ("世界观", setup.get("world")),
        ("主角设定", setup.get("protagonist")),
        ("额外要求", setup.get("extra")),
    ]
    return "\n".join(f"- {name}：{value}" for name, value in rows if value)


def outline_messages(project: dict, chapter_count: int) -> list[dict]:
    setup = project.get("setup") or {}
    user = f"""请为下面这部小说设计分章大纲。

【作品设定】
{_setup_block(setup)}

【要求】
1. 共 {chapter_count} 章，每章一个清晰的冲突或转折，章末留钩子。
2. 第一章必须在前 300 字内抓住读者，直接进入事件，不要铺垫背景。
3. 章节标题不超过 14 个字，要有画面感或悬念。
4. 只输出 JSON 数组，格式：{{"title": "章节标题", "summary": "80 字以内的剧情要点"}}
5. 不要输出任何其它文字。"""
    return [
        {"role": "system", "content": OUTLINE_SYSTEM},
        {"role": "user", "content": user},
    ]


def _previous_summary(project: dict, index: int) -> str:
    chapters = project.get("chapters") or []
    parts = []
    for i in range(max(0, index - 2), index):
        chapter = chapters[i]
        content = (chapter.get("content") or "").strip()
        if not content:
            continue
        tail = content[-300:]
        parts.append(f"第 {i + 1} 章《{chapter.get('title', '')}》结尾片段：\n{tail}")
    return "\n\n".join(parts)


def chapter_messages(project: dict, index: int, target_words: int, mode: str = "write") -> list[dict]:
    setup = project.get("setup") or {}
    outline = project.get("outline") or []
    current = outline[index] if index < len(outline) else {}
    chapter = (project.get("chapters") or [])[index] if index < len(project.get("chapters") or []) else {}
    existing = (chapter.get("content") or "").strip()

    context = [
        f"【作品设定】\n{_setup_block(setup)}",
        "【全书大纲】\n"
        + "\n".join(
            f"{i + 1}. {item.get('title', '')}：{item.get('summary', '')}"
            for i, item in enumerate(outline)
        ),
        f"【本章】第 {index + 1} 章《{current.get('title', '')}》\n剧情要点：{current.get('summary', '')}",
    ]
    previous = _previous_summary(project, index)
    if previous:
        context.append(f"【前情提要】\n{previous}")

    if mode == "continue" and existing:
        instruction = (
            f"请接着下面的正文继续写，不要重复已有内容，不要重新开头，"
            f"保持人称、语气、文风完全一致，续写约 {target_words} 字：\n\n{existing[-1500:]}"
        )
    elif mode == "rewrite" and existing:
        instruction = (
            f"请重写下面这一章，保留同样的剧情走向，但让文字更凝练、更有画面感，"
            f"约 {target_words} 字，直接输出新正文：\n\n{existing}"
        )
    else:
        instruction = (
            f"请写第 {index + 1} 章正文，约 {target_words} 字。"
            "要求：开头直接进入场景，多用对话和细节，章末留一个悬念。"
        )

    return [
        {"role": "system", "content": WRITER_SYSTEM},
        {"role": "user", "content": "\n\n".join(context) + "\n\n" + instruction},
    ]
