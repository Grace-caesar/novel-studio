"""墨语 · Novel Studio —— 一个零依赖的 AI 小说生成器。

模块划分：
    store.py    本地 JSON 存储（作品 / 章节 / 模型设置）
    prompts.py  提示词工程（大纲、正文、续写）
    llm.py      OpenAI 兼容接口的流式客户端
    demo.py     未配置 API Key 时的离线演示文本
    server.py   HTTP 服务与 REST / SSE 路由
"""

__version__ = "1.0.0"
