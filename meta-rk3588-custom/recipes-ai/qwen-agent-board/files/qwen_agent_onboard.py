#!/usr/bin/env python3
"""On-board Qwen-Agent: talks to local RKLLM and runs local shell tools."""

import json
import os
import re
import shlex
import subprocess
import sys

# Vendored aarch64 deps from the Yocto image package.
sys.path.insert(0, "/opt/qwen_agent/site-packages")

from qwen_agent.agents import Assistant
from qwen_agent.llm.schema import ASSISTANT, FunctionCall, Message
from qwen_agent.tools.base import BaseTool, register_tool

BOARD_API = "http://127.0.0.1:8080/v1"

# Deny-list: block dangerous programs / patterns; everything else is allowed.
DENIED_CMDS = {
    "rm", "rmdir", "unlink",
    "dd",
    "mkfs", "mkfs.ext4", "mkfs.ext3", "mkfs.ext2", "mkfs.xfs", "mkfs.vfat", "mkfs.btrfs",
    "fdisk", "parted", "sfdisk", "wipefs", "sgdisk",
    "reboot", "shutdown", "poweroff", "halt", "init", "telinit",
    "passwd", "useradd", "userdel", "usermod", "groupadd", "groupdel",
    "crontab", "systemctl",  # avoid stopping critical services by accident
    "insmod", "rmmod", "modprobe",
    "mkswap", "swapon", "swapoff",
    "chroot",
}

DENIED_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?/+",          # rm -rf /
    r"\bdd\b.*\bof=/dev/",                             # dd to block device
    r">\s*/dev/sd",                                    # redirect wipe disks
    r"\bmkfs\b",
    r"\bwipefs\b",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",                    # fork bomb
]


def _is_dangerous(cmd: str, tokens: list):
    prog = tokens[0]
    # strip path: /bin/rm -> rm
    base = prog.rsplit("/", 1)[-1]
    if base in DENIED_CMDS or prog in DENIED_CMDS:
        return f"error: command '{base}' is blocked as dangerous"
    # also block denied names appearing as later tokens after sudo/busybox/env
    wrappers = {"sudo", "busybox", "env", "nice", "nohup", "stdbuf", "time"}
    for i, t in enumerate(tokens):
        b = t.rsplit("/", 1)[-1]
        if b in DENIED_CMDS and (i == 0 or tokens[0].rsplit("/", 1)[-1] in wrappers):
            return f"error: command '{b}' is blocked as dangerous"
    for pat in DENIED_PATTERNS:
        if re.search(pat, cmd):
            return f"error: command matches blocked dangerous pattern"
    return None


@register_tool("run_board_cmd")
class RunBoardCmd(BaseTool):
    description = (
        "在本机（RK3588 开发板）执行一条 shell 命令。"
        "除危险命令（如 rm/dd/mkfs/reboot/shutdown/passwd 等）外均可执行。"
        "适合查看与调试：df、free、uname、ps、cat、ls、ip 等。"
    )
    parameters = [{
        "name": "command",
        "type": "string",
        "description": "要执行的完整命令，例如: df -h 或 cat /proc/cpuinfo",
        "required": True,
    }]

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json.loads(params) if isinstance(params, str) else (params or {})
        except Exception:
            args = {"command": params}
        cmd = (args.get("command") or "").strip()
        if not cmd:
            return "error: empty command"
        try:
            tokens = shlex.split(cmd)
        except ValueError as e:
            return f"error: failed to parse command: {e}"
        if not tokens:
            return "error: empty command"
        bad = _is_dangerous(cmd, tokens)
        if bad:
            return bad
        try:
            p = subprocess.run(
                tokens,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "error: command timeout (30s)"
        except FileNotFoundError:
            return f"error: binary not found: {tokens[0]}"
        except Exception as e:
            return f"error: {e}"

        out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        out = out.strip()
        if len(out) > 4000:
            out = out[:4000] + "\n...[truncated]"
        if p.returncode != 0 and not out:
            return f"error: exit={p.returncode}"
        return out or f"(empty output, exit={p.returncode})"


def build_bot(with_tools: bool = True) -> Assistant:
    os.environ.setdefault("QWEN_AGENT_MAX_LLM_CALL_PER_RUN", "2")
    llm_cfg = {
        "model": "Qwen2.5-Coder-3B",
        "model_server": BOARD_API,
        "api_key": "EMPTY",
        "model_type": "oai",
        "generate_cfg": {
            "top_p": 0.8,
            "max_tokens": 512,
            "use_raw_api": True,
            "extra_body": {"enable_thinking": False},
        },
    }
    tools = ["run_board_cmd"] if with_tools else []
    bot = Assistant(
        llm=llm_cfg,
        name="RK3588 On-Board Agent",
        description="Qwen2.5-Coder-3B Agent on RK3588 NPU via RKLLM",
        system_message=(
            "你是运行在 RK3588 开发板上的本地编程助手（Qwen2.5-Coder-3B）。"
            "回答要简洁、紧扣用户问题；写代码时给出可直接运行的片段。\n"
            "工具规则：\n"
            "1) 仅当确实需要查看/操作系统时，才调用 run_board_cmd；"
            "闲聊、自我介绍、纯写代码不要调用工具。\n"
            "2) 调用时 arguments 必须是 {\"command\":\"...\"}。"
            "查内存：free -h；查时间：date；查磁盘：df -h；"
            "查发行版：cat /etc/os-release。\n"
            "3) 拿到工具返回结果后，用一两句中文直接回答用户，"
            "不要再次调用同一个工具，不要再输出 JSON。\n"
            "4) 危险命令（rm/dd/mkfs/reboot 等）会被拒绝。"
        ),
        function_list=tools,
    )

    # use_raw_api always calls _chat_stream (SSE). With RKLLM+tools the OpenAI
    # stream iterator often hangs after the answer is already complete, so the
    # Agent never emits the final reply and the PC client never returns to 你>.
    # Force a non-stream HTTP round-trip, then yield once (including tool_calls).
    llm = bot.llm

    def _chat_stream_via_no_stream(messages, delta_stream, generate_cfg):
        cfg = dict(generate_cfg or {})
        cfg.pop("stream", None)
        oai_messages = llm.convert_messages_to_dicts(messages)
        response = llm._chat_complete_create(
            model=llm.model,
            messages=oai_messages,
            stream=False,
            **cfg,
        )
        msg = response.choices[0].message
        out = []
        content = getattr(msg, "content", None)
        if content:
            out.append(Message(role=ASSISTANT, content=content))
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            out.append(
                Message(
                    role=ASSISTANT,
                    content="",
                    function_call=FunctionCall(
                        name=fn.name or "",
                        arguments=fn.arguments or "{}",
                    ),
                    extra={"function_id": getattr(tc, "id", None) or "1"},
                )
            )
        if not out:
            out = [Message(role=ASSISTANT, content=content or "")]
        yield out

    llm._chat_stream = _chat_stream_via_no_stream
    return bot


def ask(bot: Assistant, query: str, verbose: bool = True) -> str:
    messages = [{"role": "user", "content": query}]
    last = []
    for chunk in bot.run(messages=messages):
        last = chunk

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
            content = str(m.get("content", ""))
            if len(content) > 500:
                content = content[:500] + "...[truncated]"
            tool_notes.append(f"[tool {m.get('name')} => {content}]")
    if verbose and tool_notes:
        print("TOOLS:", " ".join(tool_notes))
    if texts:
        return texts[-1]
    if tool_notes:
        return " ".join(tool_notes)
    return str(last)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="On-board Qwen-Agent demo")
    parser.add_argument("query", nargs="?", default="用一句话介绍你自己")
    parser.add_argument("--no-tools", action="store_true")
    args = parser.parse_args()

    bot = build_bot(with_tools=not args.no_tools)
    print("USER:", args.query)
    print("BOT :", ask(bot, args.query))
