"""演示模式。

没填 API Key 时，网站依然要能动起来 —— 面试官 clone 下来直接运行就能看到
完整流程，不需要去申请密钥。这里用模板拼出「像模像样」的大纲和正文，
并按字符切片模拟流式输出。
"""

from __future__ import annotations

import re
import time

_OUTLINE_TITLES = [
    "雨夜来客",
    "不该存在的信",
    "城门外的人",
    "三更灯火",
    "旧伤",
    "失控的那一夜",
    "第二次选择",
    "破晓之前",
    "空椅子",
    "最后一封信",
    "雪停的时候",
    "回家",
]


def _hero_name(project: dict) -> str:
    raw = ((project.get("setup") or {}).get("protagonist") or "").strip()
    if not raw:
        return "他"
    first = re.split(r"[，,、。；;\s]", raw)[0]
    return first[:4] or "他"


def _premise(project: dict) -> str:
    text = ((project.get("setup") or {}).get("premise") or "").strip()
    return text or "一个被命运推着往前走的人，必须在失去一切之前做出选择"


def demo_outline(project: dict, count: int) -> list[dict]:
    premise = _premise(project)
    hero = _hero_name(project)
    beats = [
        f"{hero}在一个反常的雨夜遇到改变命运的人，故事由此展开：{premise}",
        f"{hero}发现一条不该存在的线索，开始怀疑身边所有人的动机。",
        f"{hero}第一次正面遭遇阻力，代价比想象中更重。",
        f"在一次看似平静的夜里，{hero}做出了第一个无法回头的决定。",
        f"旧日伤口被重新揭开，{hero}意识到自己一直被人利用。",
        f"局势失控，{hero}必须在两个都错误的选项之间选一个。",
        f"{hero}付出代价换回一次机会，却发现对方另有目的。",
        f"真相浮出水面一半，{hero}选择了暂时沉默。",
        f"所有人都在等{hero}表态，而他只留下一个空椅子。",
        f"一封迟到的信解释了所有误会，但已经来不及了。",
        f"雪停的时候，{hero}终于看清自己真正想要的东西。",
        f"故事回到起点，{hero}这一次没有回头。",
    ]
    result = []
    for index in range(max(1, min(count, 40))):
        title = _OUTLINE_TITLES[index % len(_OUTLINE_TITLES)]
        summary = beats[index % len(beats)]
        result.append({"title": f"{title}", "summary": summary})
    return result


_PARAGRAPHS = [
    "雨是从傍晚开始下的，到深夜也没停。{hero}站在檐下，看雨水顺着瓦片连成一条线，砸在青石板上，碎成更细的白。空气里有股潮湿的铁锈味，像是谁把什么藏在了雨里。",
    "“你迟到了。”屋檐深处的影子开口，声音很轻，却压过了雨声。{hero}没有回头，只是把手往袖子里又缩了缩——那里藏着一件不能见光的东西。",
    "对方沉默了很久，久到{hero}以为这场对话已经结束。“你确定要这么做？”影子往前走了半步，停在灯光边缘，“一旦开始，就没有回头路了。”",
    "{hero}笑了一下，笑意很浅。“我从来就没有过回头路。”话音落下的时候，远处传来一声闷响，像有什么东西被彻底打开了。",
    "他们沿着墙根往外走，脚下的水洼把两个人的影子拉得很长。{hero}忽然停住，弯腰从水里捡起一样东西——那是一枚已经锈透的铜扣，背面刻着一个被磨平的姓氏。",
    "“这东西不该在这里。”影子的声音变了调。{hero}把它攥进掌心，指节因为用力而发白：“所以，它才在这里。”",
    "雨小了下去，风却起来了。街口的灯笼被吹得摇摇晃晃，光在墙上划出一道又一道弧。{hero}站在那片摇晃的光里，第一次觉得自己看清了什么。",
    "天快亮的时候，他们分开了。{hero}没有回头，只把那枚铜扣塞进衣襟最里面，贴着心口。身后的城市在雨里慢慢醒来，而属于他的那一夜，才刚刚开始。",
]


def demo_chapter(project: dict, index: int, mode: str = "write", extra_tail: str = ""):
    """按字符切片 yield，模拟流式输出。"""
    hero = _hero_name(project)

    header = "【演示模式】以下内容由内置模板生成，配置 API Key 后即为真实模型创作。\n\n"
    body = "\n\n".join(p.format(hero=hero) for p in _PARAGRAPHS[index % 2 : index % 2 + 6])
    if mode == "continue":
        text = "\n\n" + body
    elif mode == "rewrite":
        text = header + body
    else:
        text = header + body
    if extra_tail:
        text += "\n\n" + extra_tail

    buffer = ""
    for char in text:
        buffer += char
        if len(buffer) >= 8:
            yield buffer
            buffer = ""
            time.sleep(0.012)
    if buffer:
        yield buffer
