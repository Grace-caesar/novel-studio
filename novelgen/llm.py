"""OpenAI 兼容接口的流式客户端（仅用标准库）。

任何兼容 /chat/completions 的服务都能用：DeepSeek、OpenAI、通义、月之暗面、
以及各种中转站。只要在设置里填 base_url 和 model 即可。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class LLMError(Exception):
    """接口调用失败，消息可以直接展示给用户。"""


def endpoint_for(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise LLMError("还没有配置 API 地址，请点左下角「模型设置」填写 base_url")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1") or url.endswith("/compatible-mode/v1"):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


def stream_chat(settings: dict, messages: list[dict], timeout: int = 180):
    """逐段 yield 模型输出。遇到任何异常都抛 LLMError（消息可直接给用户看）。"""
    payload = {
        "model": settings.get("model") or "deepseek-chat",
        "messages": messages,
        "stream": True,
    }
    try:
        payload["temperature"] = float(settings.get("temperature") or 0.9)
        if settings.get("max_tokens"):
            payload["max_tokens"] = int(settings["max_tokens"])
    except (TypeError, ValueError):
        pass

    request = urllib.request.Request(
        endpoint_for(settings.get("base_url", "")),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.get('api_key', '')}",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise LLMError(f"接口返回 {exc.code}：{detail}") from None
    except urllib.error.URLError as exc:
        raise LLMError(f"无法连接接口：{exc.reason}") from None
    except TimeoutError:
        raise LLMError("接口连接超时，请检查网络或代理设置") from None

    produced = False
    with response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                payload_obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            choices = payload_obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                produced = True
                yield piece

    if not produced:
        raise LLMError("模型没有返回内容，请检查 model 名称是否正确")
