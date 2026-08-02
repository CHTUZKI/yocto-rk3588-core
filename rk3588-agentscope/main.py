#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentScope 板端 Qwen3 Agent —— 命令行交互界面。

在 PC/WSL 或板端均可运行。自动检测模型服务地址。
参考 rk3588-agent-chat 的终端体验：颜色输出、prompt_toolkit 中文输入、
流式 delta、工具调用状态、思考中 spinner、Ctrl+C 打断。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
except ImportError:
    PromptSession = None
    HTML = None

from agentscope.agent import Agent, ReActConfig
from agentscope.credential import OpenAICredential
from agentscope.event import (
    ReplyEndEvent,
    ReplyStartEvent,
    TextBlockDeltaEvent,
    ThinkingBlockDeltaEvent,
    ThinkingBlockStartEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg, TextBlock
from agentscope.model import OpenAIChatModel
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.permission._context import AdditionalWorkingDirectory
from agentscope.state import AgentState
from agentscope.tool import FunctionTool, Toolkit

import config
from board_tools import (
    diagnose_network,
    list_directory,
    read_board_file,
    read_text_file,
    restart_service,
    run_board_command,
    run_python_file,
    set_system_time,
    sync_ntp,
    write_text_file,
)

# ---------------------------------------------------------------------------
# Terminal styling (ported from rk3588-agent-chat)
# ---------------------------------------------------------------------------
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"

    @classmethod
    def enable(cls, on: bool) -> None:
        if not on:
            cls.RESET = cls.BOLD = cls.DIM = ""
            cls.CYAN = cls.GREEN = cls.YELLOW = cls.RED = ""
            cls.MAGENTA = cls.BLUE = ""


Style.enable(_USE_COLOR)


def cprint(text: str, *colors: str, end: str = "\n") -> None:
    print(f"{''.join(colors)}{text}{Style.RESET}", end=end, flush=True)


def clear_line() -> None:
    """Clear the current terminal line (used to wipe spinner)."""
    print("\r" + " " * 64 + "\r", end="", flush=True)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是运行在 RK3588 开发板上的本地编程助手，具备真正的诊断和修复能力。

你必须真正完成用户要求，而不是只给操作建议：
1. 用户要求写代码并运行时，先用 write_text_file 保存代码，再用 run_python_file 执行，并根据真实输出回答。
2. 用户要求保存、修改或查看程序时，使用 workspace 中的文件工具，不要使用 vi，不要让用户手动复制代码。
3. 用户说"这个文件""这个程序""刚才的命令"时，结合当前对话和已执行工具继续操作，不要无故反问。
4. 先完成工具动作，再简洁说明结果；不要伪造运行结果。
5. write_text_file / run_python_file 只能操作 Agent workspace 内的文件。

工具选择规则（重要，避免选错工具）：
- 列目录、看文件夹里有什么 → 用 list_directory（支持任意路径，如 /home、/opt、/etc）
- 读 workspace 内的代码/文本文件 → 用 read_text_file
- 读 workspace 外的板卡文件（如 /etc/hostname、/proc/cpuinfo、/opt/models/ 下的文件）→ 用 read_board_file
- 写文件、改文件 → 用 write_text_file（仅限 workspace）
- 运行 Python 脚本 → 用 run_python_file（仅限 workspace）
- 运行系统命令 → 用 run_board_command（支持管道 |、重定向 > <、链式 && || ; 、命令替换 $() ）
- 设置系统时间 → 用 set_system_time（板子无 RTC，断电后时间会错，导致 HTTPS 失败）
- NTP 同步时间 → 用 sync_ntp（网络可用时优先用这个）
- 重启服务 → 用 restart_service（白名单：rkllm-server、networking、systemd-timesyncd、systemd-resolved、sshd）
- 网络诊断 → 用 diagnose_network（一键输出完整网络报告：网卡、路由、DNS、ping、HTTPS、时间）

排查和修复规则（重要）：
- 用户报告问题时，先用诊断工具看真实状态，不要猜。比如网络问题先用 diagnose_network，时间问题先 date。
- 看到错误要追根因。比如 curl 报 SSL 证书错误（exit 60）→ 检查 date → 时间不对 → set_system_time 或 sync_ntp → 重试。
- run_board_command 支持完整 shell 语法，可以组合命令排查，比如 "ip addr && ip route && ping -c 2 8.8.8.8"。
- rm/rmdir/unlink 被禁用（eMMC 上无撤销）。需要删除文件时，告知用户手动删除。
- 不要编造工具结果。如果工具返回了输出，必须基于真实输出回答。

重要规则：
- 不要重复调用同一个工具。如果工具已经返回结果，请根据结果直接用文字回答用户，不要再次调用相同工具。
- 只有用户明确要求创建文件、运行代码、查看系统状态、查看目录或文件、排查问题时才使用工具。简单问答（如数学计算、知识解释、闲聊）不需要任何工具，直接用文字回答。
- 回答时不要输出 JSON 代码块，直接用中文文字回答。
"""

# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------

def build_agent() -> Agent:
    Path(config.WORKSPACE).mkdir(parents=True, exist_ok=True)
    toolkit = Toolkit(
        tools=[
            FunctionTool(write_text_file, is_read_only=False),
            FunctionTool(read_text_file, is_read_only=True),
            FunctionTool(read_board_file, is_read_only=True),
            FunctionTool(list_directory, is_read_only=True),
            FunctionTool(run_python_file, is_read_only=False),
            FunctionTool(run_board_command, is_read_only=False),
            FunctionTool(set_system_time, is_read_only=False),
            FunctionTool(sync_ntp, is_read_only=False),
            FunctionTool(restart_service, is_read_only=False),
            FunctionTool(diagnose_network, is_read_only=True),
        ]
    )
    model = OpenAIChatModel(
        credential=OpenAICredential(
            api_key=config.API_KEY,
            base_url=config.MODEL_SERVER,
        ),
        model=config.MODEL,
        parameters=OpenAIChatModel.Parameters(
            max_tokens=config.MAX_TOKENS,
            thinking_enable=config.ENABLE_THINKING,
            temperature=0.7,
            top_p=0.8,
            parallel_tool_calls=False,
        ),
        stream=True,
        formatter=OpenAIChatFormatter(),
        client_kwargs={"timeout": 180.0},
        extra_body={
            "enable_thinking": config.ENABLE_THINKING,
            "chat_template_kwargs": {"enable_thinking": config.ENABLE_THINKING},
        },
        context_size=4096,
    )
    state = AgentState()
    state.permission_context = PermissionContext(
        mode=PermissionMode.BYPASS,
        working_directories={
            config.WORKSPACE: AdditionalWorkingDirectory(
                path=config.WORKSPACE,
                source="session",
            )
        },
    )
    return Agent(
        name="RK3588 AgentScope Agent",
        system_prompt=SYSTEM_PROMPT,
        model=model,
        toolkit=toolkit,
        state=state,
        react_config=ReActConfig(max_iters=5),
    )


# ---------------------------------------------------------------------------
# Input helper (ported from rk3588-agent-chat)
# ---------------------------------------------------------------------------

_pt_session: "PromptSession | None" = None


def _get_pt_session() -> "PromptSession":
    global _pt_session
    if _pt_session is None:
        _pt_session = PromptSession()
    return _pt_session


async def read_user_line() -> str:
    """Read a line with prompt_toolkit for proper CJK width/backspace."""
    if PromptSession is not None and sys.stdin.isatty():
        session = _get_pt_session()
        if _USE_COLOR:
            return (await session.prompt_async(HTML("<ansicyan><b>你&gt;</b></ansicyan> "))).strip()
        return (await session.prompt_async("你> ")).strip()
    # Fallback: raw stdin buffer with UTF-8 errors=replace (in thread)
    def _raw_read() -> str:
        sys.stdout.write("你> ")
        sys.stdout.flush()
        raw = sys.stdin.buffer.readline()
        if not raw:
            raise EOFError
        return raw.decode("utf-8", errors="replace").strip()
    return await asyncio.to_thread(_raw_read)


def print_help() -> None:
    cprint("命令:", Style.BOLD, Style.BLUE)
    print(
        f"  {Style.CYAN}/help{Style.RESET}     显示帮助\n"
        f"  {Style.CYAN}/clear{Style.RESET}    清空对话历史\n"
        f"  {Style.CYAN}/quit{Style.RESET}     退出\n"
        f"  {Style.CYAN}Ctrl+C{Style.RESET}   生成中打断；在输入提示符再按一次退出\n"
        "直接输入中文即可与 Agent 对话（支持流式输出和工具调用显示）。"
    )


# ---------------------------------------------------------------------------
# Streaming reply handler (ported from rk3588-agent-chat handle_chat_stream)
# ---------------------------------------------------------------------------

_SPINNER = "|/-\\"


async def _spin(started: float) -> None:
    """Show a spinner line. Caller must clear it before printing real output."""
    spin_i = 0
    while True:
        ch = _SPINNER[spin_i % len(_SPINNER)]
        elapsed = time.time() - started
        msg = f"Agent> {ch} 思考中... {elapsed:.1f}s（Ctrl+C 打断）"
        print(f"\r{Style.DIM}{Style.YELLOW}{msg}{Style.RESET}", end="", flush=True)
        spin_i += 1
        await asyncio.sleep(0.2)


async def handle_reply_stream(agent: Agent, user_msg: Msg, timeout: float = 600.0) -> None:
    """Consume agent.reply_stream events with spinner, deltas, tool calls.

    Displays tool call arguments and real tool results (not just names),
    so the user can verify what actually happened — like OpenCode's
    transparent command/output display.
    """
    prefix = f"{Style.GREEN}{Style.BOLD}Agent> {Style.RESET}" if _USE_COLOR else "Agent> "
    started = time.time()
    first_output = True  # no real output printed yet

    # Track tool call arguments and results by tool_call_id
    tool_call_args: dict[str, str] = {}   # tool_call_id -> accumulated JSON args
    tool_call_names: dict[str, str] = {}  # tool_call_id -> tool name
    tool_results: dict[str, str] = {}     # tool_call_id -> accumulated result text

    stream = agent.reply_stream(user_msg)
    spinner_task: asyncio.Task | None = asyncio.create_task(_spin(started))
    stream_closed = False

    try:
        while True:
            try:
                event = await asyncio.wait_for(stream.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise TimeoutError("等待 Agent 响应超时")

            # Cancel spinner on first real output
            if spinner_task and not isinstance(event, ReplyStartEvent):
                spinner_task.cancel()
                spinner_task = None
                clear_line()

            # --- Text delta (model output) ---
            if isinstance(event, TextBlockDeltaEvent):
                if first_output:
                    print(prefix, end="", flush=True)
                    first_output = False
                print(event.delta, end="", flush=True)
                continue

            # --- Thinking block (reasoning model) ---
            if isinstance(event, ThinkingBlockStartEvent):
                if not first_output:
                    print(flush=True)
                cprint("思考中...", Style.DIM, Style.YELLOW)
                first_output = False
                continue
            if isinstance(event, ThinkingBlockDeltaEvent):
                print(f"{Style.DIM}{event.delta}{Style.RESET}", end="", flush=True)
                continue

            # --- Tool call start: record name, start accumulating args ---
            if isinstance(event, ToolCallStartEvent):
                if not first_output:
                    print(flush=True)
                tool_call_names[event.tool_call_id] = event.tool_call_name
                tool_call_args[event.tool_call_id] = ""
                first_output = False
                continue

            # --- Tool call delta: accumulate JSON argument fragments ---
            if isinstance(event, ToolCallDeltaEvent):
                tool_call_args[event.tool_call_id] += event.delta
                continue

            # --- Tool call end: display the tool call with its arguments ---
            if isinstance(event, ToolCallEndEvent):
                tid = event.tool_call_id
                name = tool_call_names.get(tid, "?")
                args_json = tool_call_args.get(tid, "")
                # Try to pretty-print the arguments
                args_display = _format_tool_args(name, args_json)
                cprint(f"工具调用: {name}", Style.MAGENTA, Style.BOLD)
                if args_display:
                    cprint(f"  {args_display}", Style.DIM, Style.MAGENTA)
                continue

            # --- Tool result start: start accumulating result text ---
            if isinstance(event, ToolResultStartEvent):
                tool_results[event.tool_call_id] = ""
                continue

            # --- Tool result text delta: accumulate result fragments ---
            if isinstance(event, ToolResultTextDeltaEvent):
                tool_results[event.tool_call_id] += event.delta
                continue

            # --- Tool result end: display the real result ---
            if isinstance(event, ToolResultEndEvent):
                tid = event.tool_call_id
                name = tool_call_names.get(tid, "?")
                result_text = tool_results.get(tid, "").strip()
                cprint(f"工具结果: {name}", Style.DIM, Style.MAGENTA)
                if result_text:
                    # Show the real output, indented and truncated
                    lines = result_text.split("\n")
                    if len(lines) > 30:
                        lines = lines[:30] + [f"...[{len(lines)-30} more lines]"]
                    for line in lines:
                        if len(line) > 200:
                            line = line[:200] + "..."
                        cprint(f"  {line}", Style.DIM)
                else:
                    cprint("  (无输出)", Style.DIM)
                continue

            # --- Reply end ---
            if isinstance(event, ReplyEndEvent):
                if not first_output:
                    print(flush=True)
                if event.finished_reason == "exceed_max_iters":
                    cprint("Agent> 达到最大迭代次数。", Style.YELLOW)
                elif event.error:
                    cprint(f"Agent> 错误: {event.error}", Style.RED, Style.BOLD)
                stream_closed = True
                return

            # ReplyStartEvent and other events: no output
            if isinstance(event, ReplyStartEvent):
                continue

        # Stream ended without ReplyEndEvent
        if not first_output:
            print(flush=True)
        stream_closed = True

    except KeyboardInterrupt:
        if spinner_task:
            spinner_task.cancel()
        clear_line()
        if not first_output:
            print(flush=True)
        cprint("（已打断）", Style.YELLOW)
        raise
    except asyncio.CancelledError:
        if spinner_task:
            spinner_task.cancel()
        clear_line()
        if not first_output:
            print(flush=True)
        raise
    finally:
        if spinner_task:
            spinner_task.cancel()
        # Only aclose if the stream wasn't cleanly exhausted/returned
        if not stream_closed:
            try:
                await stream.aclose()
            except Exception:
                pass


def _format_tool_args(tool_name: str, args_json: str) -> str:
    """Format tool call arguments for display, like OpenCode shows commands."""
    if not args_json:
        return ""
    try:
        import json
        args = json.loads(args_json)
    except Exception:
        return args_json[:200]

    # Tool-specific pretty printing
    if tool_name == "run_board_command" and "command" in args:
        return f"$ {args['command']}"
    if tool_name == "list_directory" and "path" in args:
        return f"ls {args['path']}"
    if tool_name == "read_board_file" and "path" in args:
        return f"cat {args['path']}"
    if tool_name == "read_text_file" and "path" in args:
        return f"cat {args['path']}"
    if tool_name == "write_text_file" and "path" in args:
        content_preview = (args.get("content", "") or "")[:60]
        if len(args.get("content", "") or "") > 60:
            content_preview += "..."
        return f"write {args['path']}  ({len(args.get('content','') or '')} bytes)"
    if tool_name == "run_python_file" and "path" in args:
        return f"python3 {args['path']}"
    if tool_name == "set_system_time" and "time_str" in args:
        return f"date -s '{args['time_str']}'"
    if tool_name == "sync_ntp":
        return f"ntpdate {args.get('server', 'pool.ntp.org')}"
    if tool_name == "restart_service" and "name" in args:
        return f"systemctl restart {args['name']}"
    if tool_name == "diagnose_network":
        return "network diagnostic report"

    # Generic: show all args
    try:
        import json
        return json.dumps(args, ensure_ascii=False)[:200]
    except Exception:
        return args_json[:200]


# ---------------------------------------------------------------------------
# Main chat loop
# ---------------------------------------------------------------------------

async def chat() -> None:
    agent = build_agent()
    cprint(f"AgentScope 已连接 Qwen3：{config.MODEL_SERVER}", Style.GREEN)
    cprint(f"workspace：{config.WORKSPACE}", Style.DIM)
    print_help()
    cprint("-" * 40, Style.DIM)

    while True:
        try:
            user_text = await read_user_line()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_text:
            continue
        if user_text in ("/quit", "/exit", "exit", "quit"):
            cprint("已退出。", Style.DIM)
            break
        if user_text == "/help":
            print_help()
            continue
        if user_text == "/clear":
            agent.state.context = []
            agent.state.summary = ""
            cprint("Agent> 已清空会话。", Style.GREEN)
            continue

        user_msg = Msg(
            name="user",
            content=[TextBlock(type="text", text=user_text)],
            role="user",
        )

        try:
            await handle_reply_stream(agent, user_msg, timeout=600)
        except KeyboardInterrupt:
            # Already handled in handle_reply_stream
            continue
        except Exception as exc:
            clear_line()
            cprint(f"Agent> 错误：{type(exc).__name__}: {exc}", Style.RED, Style.BOLD)
            continue


if __name__ == "__main__":
    # Suppress the harmless "async generator ignored GeneratorExit" warning
    # that AgentScope's internal generators may emit during shutdown.
    import logging
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    try:
        asyncio.run(chat())
    except KeyboardInterrupt:
        pass
