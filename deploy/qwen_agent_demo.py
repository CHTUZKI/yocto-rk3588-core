#!/usr/bin/env python3
"""Qwen-Agent demo talking to RK3588 RKLLM OpenAI-compatible server."""

from qwen_agent.agents import Assistant
from qwen_agent.tools.base import BaseTool, register_tool


BOARD_API = "http://192.168.1.14:8080/v1"


@register_tool("get_board_time")
class GetBoardTime(BaseTool):
    description = "获取当前主机本地时间（演示用工具）"
    parameters = []

    def call(self, params: str, **kwargs) -> str:
        import datetime
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_bot(with_tools: bool = True) -> Assistant:
    llm_cfg = {
        "model": "Qwen3-4B",
        "model_server": BOARD_API,
        "api_key": "EMPTY",
        "model_type": "oai",
        "generate_cfg": {
            # Qwen3 + small on-device model: keep replies short and non-thinking
            "top_p": 0.8,
            "max_tokens": 512,
            # Send tools via OpenAI tools= so RKLLM set_function_tools is used
            "use_raw_api": True,
            "extra_body": {
                "enable_thinking": False,
            },
        },
    }
    tools = ["get_board_time"] if with_tools else []
    return Assistant(
        llm=llm_cfg,
        name="RK3588 Assistant",
        description="Local Qwen3-4B on RK3588 NPU via RKLLM",
        system_message=(
            "你是运行在 RK3588 开发板上的本地助手。"
            "回答要简洁。需要当前时间时，调用 get_board_time 工具。"
        ),
        function_list=tools,
    )


def ask(bot: Assistant, query: str) -> str:
    messages = [{"role": "user", "content": query}]
    last = []
    for chunk in bot.run(messages=messages):
        last = chunk

    # Prefer final plain-text assistant reply; otherwise summarize tool trail.
    texts = []
    tool_notes = []
    for m in last:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "assistant":
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                texts.append(c.strip())
            fc = m.get("function_call")
            if fc:
                tool_notes.append(f"[call {fc.get('name')}({fc.get('arguments')})]")
        elif role == "function":
            tool_notes.append(f"[tool {m.get('name')} => {m.get('content')}]")
    if texts:
        return texts[-1]
    if tool_notes:
        return " ".join(tool_notes)
    return str(last)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="用一句话介绍你自己")
    parser.add_argument("--no-tools", action="store_true")
    args = parser.parse_args()

    bot = build_bot(with_tools=not args.no_tools)
    print("USER:", args.query)
    print("BOT :", ask(bot, args.query))
