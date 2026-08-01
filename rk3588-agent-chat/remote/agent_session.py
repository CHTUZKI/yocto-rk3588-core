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
    {"ok":true,"event":"done","reply":"...","tools":"..."}  # 本轮结束（立刻回到提示符）
    {"ok":false,"error":"..."}
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
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
    r'^\s*(?:```(?:json)?\s*)?\{?\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:',
    re.DOTALL | re.IGNORECASE,
)


def _looks_like_raw_tool_json(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "<tool_call>" in t:
        return True
    if "```" in t and '"name"' in t and '"arguments"' in t:
        return True
    return bool(_TOOL_JSON_RE.match(t))


def _msg_role(m) -> str:
    if isinstance(m, dict):
        return m.get("role") or ""
    return getattr(m, "role", "") or ""


def _msg_content(m) -> str:
    if isinstance(m, dict):
        c = m.get("content")
    else:
        c = getattr(m, "content", None)
    return c if isinstance(c, str) else ""


def _msg_function_call(m):
    if isinstance(m, dict):
        return m.get("function_call")
    return getattr(m, "function_call", None)


def _msg_name(m) -> str:
    if isinstance(m, dict):
        return m.get("name") or "tool"
    return getattr(m, "name", None) or "tool"


def _latest_assistant_content(messages: list) -> str:
    for m in reversed(messages or []):
        if _msg_role(m) == "assistant":
            c = _msg_content(m)
            if c:
                return c
    return ""


def _extract_reply(last: list) -> tuple[str, str]:
    texts = []
    tool_notes = []
    last_tool_out = ""
    for m in last:
        role = _msg_role(m)
        if role == "assistant":
            c = _msg_content(m)
            if c.strip() and not _looks_like_raw_tool_json(c):
                texts.append(c.strip())
            fc = _msg_function_call(m)
            if fc:
                if isinstance(fc, dict):
                    tool_notes.append(f"[call {fc.get('name')}({fc.get('arguments')})]")
                else:
                    tool_notes.append(
                        f"[call {getattr(fc, 'name', '')}({getattr(fc, 'arguments', '')})]"
                    )
        elif role == "function":
            content = _msg_content(m) or str(getattr(m, "content", ""))
            last_tool_out = content
            shown = content if len(content) <= 500 else content[:500] + "...[truncated]"
            tool_notes.append(f"[tool {_msg_name(m)} => {shown}]")

    tools = " ".join(tool_notes)
    if texts:
        return texts[-1], tools
    if last_tool_out.strip():
        shown = last_tool_out.strip()
        if len(shown) > 1200:
            shown = shown[:1200] + "...[truncated]"
        return shown, tools
    if tool_notes:
        return "工具已执行：" + tools, tools
    return str(last), tools


def ask_turn(bot, history: list, query: str) -> tuple[str, str]:
    """
    history 只保存纯 user/assistant 文本轮次，保证下一轮始终以 user 开头。
    运行中通过 emit(delta/status/tool) 推送流式事件。
    答完立即 emit event=done，并在后台关闭 generator，避免卡住 PC 端提示符。
    """
    turn_messages = list(history)
    turn_messages.append({"role": "user", "content": query})

    while turn_messages and turn_messages[0].get("role") != "user":
        turn_messages.pop(0)

    last = []
    prev_content = ""
    in_tool_stream = False
    seen_tool_note = set()
    done_emitted = False

    gen = bot.run(messages=turn_messages)
    try:
        for chunk in gen:
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
                    if in_tool_stream:
                        in_tool_stream = False
                        prev_content = ""
                        delta = content
                    if delta:
                        emit({"ok": True, "event": "delta", "text": delta})
                prev_content = content
            elif content and content != prev_content:
                if not _looks_like_raw_tool_json(content):
                    emit({"ok": True, "event": "delta", "text": content})
                prev_content = content

            for m in last:
                if _msg_role(m) != "function":
                    continue
                name = _msg_name(m)
                raw = _msg_content(m)
                key = f"{name}:{raw[:80]}"
                if key in seen_tool_note:
                    continue
                seen_tool_note.add(key)
                shown = raw if len(raw) <= 300 else raw[:300] + "...[truncated]"
                emit({"ok": True, "event": "tool", "text": f"{name} => {shown}"})

            has_fn_call = any(
                _msg_role(m) == "assistant" and _msg_function_call(m) for m in (last or [])
            )
            if (
                content
                and not _looks_like_raw_tool_json(content)
                and not has_fn_call
                and not in_tool_stream
            ):
                reply, tools = _extract_reply(last)
                emit({"ok": True, "event": "done", "reply": reply, "tools": tools})
                done_emitted = True
                break
    finally:
        # Closing Qwen-Agent's generator can block on HTTP cleanup; never stall the prompt.
        def _cleanup(g=gen):
            try:
                g.close()
            except Exception:
                pass

        threading.Thread(target=_cleanup, daemon=True).start()

    reply, tools = _extract_reply(last)
    if not done_emitted:
        emit({"ok": True, "event": "done", "reply": reply, "tools": tools})

    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": reply})
    # Keep prefill bounded: long history costs more than it helps on a 4K context.
    while len(history) > 8:
        del history[:2]
    while sum(len(m.get("content", "")) for m in history) > 10000:
        del history[:2]
    if history and history[0].get("role") != "user":
        history.pop(0)

    return reply, tools


def main() -> int:
    # Limit tool/LLM loops: Coder-3B often re-calls the same tool without summarizing.
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
                ask_turn(bot, history, text.strip())
                # ask_turn 已通过 event=done 通知客户端，不再重复发 reply，
                # 避免客户端已回到「你>」后把迟到的 reply 当成下一轮响应。
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
