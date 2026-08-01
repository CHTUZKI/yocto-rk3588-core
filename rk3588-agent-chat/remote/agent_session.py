#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板上常驻会话：通过 stdin/stdout 收发 UTF-8 JSON 行，与本地 CLI 对话。
协议：
  本地 -> 板: {"cmd":"chat","text":"..."} / {"cmd":"ping"} / {"cmd":"quit"} / {"cmd":"clear"}
  板 -> 本地:
    {"ok":true,"event":"ready"|"pong"|"bye"|"cleared",...}
    {"ok":true,"event":"delta","text":"..."}          # 逐字增量
    {"ok":true,"event":"status","text":"..."}         # 状态（如调用工具）
    {"ok":true,"event":"tool","text":"..."}           # 工具摘要
    {"ok":true,"reply":"...","tools":"..."}           # 本轮结束
    {"ok":false,"error":"..."}
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Vendored deps + onboard module
sys.path.insert(0, "/opt/qwen_agent/site-packages")
sys.path.insert(0, "/opt/qwen_agent")

try:
    from qwen_agent_onboard import build_bot  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - PC 上打开文件时的 IDE/类型检查回退
    def build_bot(*_args, **_kwargs):  # type: ignore[misc]
        raise RuntimeError(
            "agent_session.py 应在开发板上运行；本机缺少 qwen_agent_onboard"
        )


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


_TOOL_JSON_RE = re.compile(
    r'^\s*\{?\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:',
    re.DOTALL,
)


def _looks_like_raw_tool_json(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "<tool_call>" in t:
        return True
    return bool(_TOOL_JSON_RE.match(t))


def _latest_assistant_content(messages: list) -> str:
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "assistant":
            c = m.get("content")
            if isinstance(c, str):
                return c
    return ""


def _extract_reply(last: list) -> tuple[str, str]:
    texts = []
    tool_notes = []
    for m in last:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "assistant":
            c = m.get("content")
            if isinstance(c, str) and c.strip() and not _looks_like_raw_tool_json(c):
                texts.append(c.strip())
            fc = m.get("function_call")
            if fc:
                tool_notes.append(f"[call {fc.get('name')}({fc.get('arguments')})]")
        elif role == "function":
            content = str(m.get("content", ""))
            if len(content) > 500:
                content = content[:500] + "...[truncated]"
            tool_notes.append(f"[tool {m.get('name')} => {content}]")

    tools = " ".join(tool_notes)
    if texts:
        return texts[-1], tools
    if tool_notes:
        return "工具已执行：" + tools, tools
    return str(last), tools


def ask_turn(bot, history: list, query: str) -> tuple[str, str]:
    """
    history 只保存纯 user/assistant 文本轮次，保证下一轮始终以 user 开头。
    运行中通过 emit(delta/status/tool) 推送流式事件。
    """
    turn_messages = list(history)
    turn_messages.append({"role": "user", "content": query})

    while turn_messages and turn_messages[0].get("role") != "user":
        turn_messages.pop(0)

    last = []
    prev_content = ""
    in_tool_stream = False
    seen_tool_note = set()

    for chunk in bot.run(messages=turn_messages):
        last = chunk
        content = _latest_assistant_content(last)

        if content and _looks_like_raw_tool_json(content):
            if not in_tool_stream:
                in_tool_stream = True
                emit({"ok": True, "event": "status", "text": "正在调用工具..."})
            prev_content = content
        elif content and content.startswith(prev_content):
            delta = content[len(prev_content) :]
            if delta and not _looks_like_raw_tool_json(content):
                # 工具调用结束后的正文，或纯回答
                if in_tool_stream:
                    in_tool_stream = False
                    prev_content = ""
                    delta = content  # 新一段正文从头推
                if delta:
                    emit({"ok": True, "event": "delta", "text": delta})
            prev_content = content
        elif content and content != prev_content:
            # 内容被替换（少见）：推整段差分尽力而为
            if not _looks_like_raw_tool_json(content):
                emit({"ok": True, "event": "delta", "text": content})
            prev_content = content

        # 工具结果一出现就推送摘要（去重）
        for m in last:
            if not isinstance(m, dict) or m.get("role") != "function":
                continue
            name = m.get("name") or "tool"
            raw = str(m.get("content", ""))
            key = f"{name}:{raw[:80]}"
            if key in seen_tool_note:
                continue
            seen_tool_note.add(key)
            shown = raw if len(raw) <= 300 else raw[:300] + "...[truncated]"
            emit({"ok": True, "event": "tool", "text": f"{name} => {shown}"})

    reply, tools = _extract_reply(last)

    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": reply})
    # Keep prefill bounded within the model's 4K context window.
    while len(history) > 8:
        del history[:2]
    while sum(len(m.get("content", "")) for m in history) > 10000:
        del history[:2]
    if history and history[0].get("role") != "user":
        history.pop(0)

    return reply, tools


def main() -> int:
    os.environ.setdefault("QWEN_AGENT_MAX_LLM_CALL_PER_RUN", "2")
    bot = build_bot(with_tools=True)
    history: list = []
    emit({"ok": True, "event": "ready", "reply": "板上 Agent 会话已就绪"})

    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            break
        try:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            req = json.loads(line)
        except Exception as e:
            emit({"ok": False, "error": f"invalid request: {e}"})
            continue

        cmd = req.get("cmd")
        if cmd == "quit":
            emit({"ok": True, "event": "bye"})
            break
        if cmd == "ping":
            emit({"ok": True, "event": "pong"})
            continue
        if cmd == "clear":
            history = []
            emit({"ok": True, "event": "cleared", "reply": "已清空对话历史"})
            continue
        if cmd == "chat":
            text = req.get("text", "")
            if not isinstance(text, str) or not text.strip():
                emit({"ok": False, "error": "empty text"})
                continue
            try:
                reply, tools = ask_turn(bot, history, text.strip())
                emit({"ok": True, "reply": reply, "tools": tools})
            except Exception as e:
                emit({
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-1500:],
                })
            continue

        emit({"ok": False, "error": f"unknown cmd: {cmd}"})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
