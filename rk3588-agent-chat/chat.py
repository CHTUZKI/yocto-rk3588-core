#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本机（PC / WSL）命令行客户端 —— 不在板子上运行。

自动 SSH 连接 RK3588，用 UTF-8 收发中文，与板上 Agent 对话。
板上负责：RKLLM 推理 + Agent/工具；本机负责：中文输入输出。

用法（在 PC 上）:
  cd rk3588-agent-chat
  ./run.sh
  # 或: python chat.py --host 192.168.1.14
"""

from __future__ import annotations

import argparse
import json
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
    import paramiko
except ImportError:
    print("缺少依赖 paramiko，请先安装：")
    print("  python3 -m pip install -r requirements.txt")
    print("或：")
    print("  ./run.sh")
    raise SystemExit(1)

try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.formatted_text import HTML
except ImportError:
    print("缺少依赖 prompt_toolkit（用于正确处理中文退格），请先：")
    print("  ./run.sh")
    print("或: pip install prompt_toolkit")
    raise SystemExit(1)

import config

ROOT = Path(__file__).resolve().parent
REMOTE_SESSION_LOCAL = ROOT / "remote" / "agent_session.py"

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


def connect(host: str, port: int, user: str, password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    auth_kw = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": config.CONNECT_TIMEOUT,
        "allow_agent": False,
        "look_for_keys": False,
    }
    try:
        client.connect(password=password if password is not None else "", **auth_kw)
    except paramiko.AuthenticationException:
        if password:
            client.connect(password="", **auth_kw)
        else:
            raise
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(30)
    return client


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 60) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def ensure_remote_ready(client: paramiko.SSHClient) -> None:
    """上传会话脚本，并确保板上 RKLLM HTTP 服务在跑。"""
    sftp = client.open_sftp()
    try:
        try:
            sftp.stat("/opt/qwen_agent")
        except FileNotFoundError:
            run(client, "mkdir -p /opt/qwen_agent")
        sftp.put(str(REMOTE_SESSION_LOCAL), config.REMOTE_SESSION)
        run(client, f"chmod +x {config.REMOTE_SESSION}")
    finally:
        sftp.close()

    _, out, _ = run(client, "ps | grep flask_server | grep -v grep || true", timeout=10)
    if "flask_server" not in out:
        cprint("板上 RKLLM 服务未运行，正在启动（首次加载模型可能要几十秒）...", Style.YELLOW)
        start = (
            f"cd {config.REMOTE_SERVER_DIR} && "
            f"export LD_LIBRARY_PATH={config.REMOTE_SERVER_DIR}/lib:/opt/rkllm && "
            f"nohup python3 flask_server.py "
            f"--rkllm_model_path {config.REMOTE_MODEL} "
            f"--target_platform rk3588 > /tmp/rkllm_server.log 2>&1 &"
        )
        run(client, start, timeout=10)
        for _ in range(60):
            _, o, _ = run(
                client,
                "curl -sf http://127.0.0.1:8080/v1/models >/dev/null && echo OK || true",
                timeout=10,
            )
            if "OK" in o:
                cprint("RKLLM 服务已就绪。", Style.GREEN)
                break
            time.sleep(3)
        else:
            cprint(
                "警告：等待 RKLLM 服务超时，对话可能失败。可查看板上 /tmp/rkllm_server.log",
                Style.YELLOW,
            )


def open_agent_session(client: paramiko.SSHClient):
    """打开远端 Python 会话通道（UTF-8 JSON 行协议）。"""
    remote_cmd = (
        "export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUTF8=1; "
        f"exec python3 -u {config.REMOTE_SESSION}"
    )
    transport = client.get_transport()
    assert transport is not None
    channel = transport.open_session()
    channel.set_combine_stderr(True)
    channel.exec_command(remote_cmd)
    return channel


def send_req(channel, obj: dict) -> None:
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    channel.sendall(data)


def recv_json_line(channel, timeout: float = 300.0) -> dict:
    """从 channel 读到一行完整 JSON 响应（忽略非响应行）。"""
    buf = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if channel.recv_ready():
            chunk = channel.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
            while b"\n" in buf:
                line, _, rest = buf.partition(b"\n")
                buf[:] = rest
                text = line.decode("utf-8", errors="replace").strip()
                if not text or not text.startswith("{"):
                    continue
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if any(k in obj for k in ("ok", "event", "reply", "error")):
                    return obj
        if channel.exit_status_ready() and not channel.recv_ready():
            while channel.recv_ready():
                buf.extend(channel.recv(4096))
            break
        time.sleep(0.05)
    raise TimeoutError("等待板上 Agent 响应超时")


def read_user_line(prefix: str = "你> ") -> str:
    """用 prompt_toolkit 读入一行，正确处理中文显示宽度与退格删除。"""
    if _USE_COLOR:
        return pt_prompt(HTML("<ansicyan><b>你&gt;</b></ansicyan> ")).strip()
    return pt_prompt(prefix).strip()


def print_help() -> None:
    cprint("命令:", Style.BOLD, Style.BLUE)
    print(
        f"  {Style.CYAN}/help{Style.RESET}     显示帮助\n"
        f"  {Style.CYAN}/clear{Style.RESET}    清空板上对话历史\n"
        f"  {Style.CYAN}/quit{Style.RESET}     退出\n"
        "直接输入中文即可与板上 Agent 对话。"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="RK3588 板上 Agent 中文命令行客户端")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--user", default=config.USER)
    parser.add_argument("--password", default=config.PASSWORD)
    args = parser.parse_args()

    cprint(f"正在连接 {args.user}@{args.host}:{args.port} ...", Style.DIM)
    try:
        client = connect(args.host, args.port, args.user, args.password)
    except Exception as e:
        cprint(f"SSH 连接失败: {e}", Style.RED, Style.BOLD)
        return 1

    try:
        ensure_remote_ready(client)
        cprint("正在启动板上 Agent 会话...", Style.DIM)
        channel = open_agent_session(client)

        ready = recv_json_line(channel, timeout=120)
        if not ready.get("ok"):
            cprint(f"会话启动失败: {ready}", Style.RED, Style.BOLD)
            return 1
        cprint(ready.get("reply", "就绪"), Style.GREEN)
        print_help()
        cprint("-" * 40, Style.DIM)

        while True:
            try:
                user_text = read_user_line()
            except (EOFError, KeyboardInterrupt):
                print()
                user_text = "/quit"

            if not user_text:
                continue
            if user_text in ("/quit", "/exit", "exit", "quit"):
                send_req(channel, {"cmd": "quit"})
                try:
                    recv_json_line(channel, timeout=10)
                except Exception:
                    pass
                cprint("已退出。", Style.DIM)
                break
            if user_text == "/help":
                print_help()
                continue
            if user_text == "/clear":
                send_req(channel, {"cmd": "clear"})
                resp = recv_json_line(channel, timeout=30)
                cprint(f"Agent> {resp.get('reply') or resp}", Style.GREEN)
                continue

            send_req(channel, {"cmd": "chat", "text": user_text})
            cprint("Agent> (思考/调用工具中...)", Style.DIM, Style.YELLOW)
            try:
                resp = recv_json_line(channel, timeout=600)
            except Exception as e:
                cprint(f"Agent> 错误: {e}", Style.RED, Style.BOLD)
                continue

            if not resp.get("ok"):
                cprint(f"Agent> 错误: {resp.get('error', resp)}", Style.RED, Style.BOLD)
                if resp.get("trace"):
                    cprint(resp["trace"], Style.DIM, Style.RED)
                continue

            tools = resp.get("tools") or ""
            if tools:
                cprint(f"工具: {tools}", Style.MAGENTA)
            cprint(f"Agent> {resp.get('reply', '')}", Style.GREEN, Style.BOLD)

    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
