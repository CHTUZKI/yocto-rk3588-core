#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本机（PC / WSL）命令行客户端 —— 直连板上 Qwen3（RKLLM）。

与 rk3588-agent-chat 的区别：
  - 本项目：HTTP → http://板子:8080/v1/chat/completions（纯模型对话，SSE 逐字）
  - Agent 项目：SSH → 板上 Qwen-Agent（可调工具）

用法:
  cd rk3588-qwen-chat
  ./run.sh
  # 或: python chat.py --base-url http://192.168.1.14:8080/v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Iterator

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import requests
except ImportError:
    print("缺少依赖 requests，请先：./run.sh  或  pip install -r requirements.txt")
    raise SystemExit(1)

try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.formatted_text import HTML
except ImportError:
    print("缺少依赖 prompt_toolkit，请先：./run.sh")
    raise SystemExit(1)

import config

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BLUE = "\033[34m"

    @classmethod
    def enable(cls, on: bool) -> None:
        if not on:
            cls.RESET = cls.BOLD = cls.DIM = ""
            cls.CYAN = cls.GREEN = cls.YELLOW = cls.RED = ""
            cls.BLUE = ""


Style.enable(_USE_COLOR)


def cprint(text: str, *colors: str, end: str = "\n") -> None:
    print(f"{''.join(colors)}{text}{Style.RESET}", end=end, flush=True)


def check_server(base_url: str, connect_timeout: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/models"
    r = requests.get(url, timeout=(connect_timeout, connect_timeout))
    r.raise_for_status()
    return r.json()


class GenerationInterrupted(Exception):
    """User pressed Ctrl+C while the model was generating."""


def request_abort(base_url: str) -> None:
    """Ask the board to stop RKLLM generation."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        abort_url = root + "/abort"
    else:
        abort_url = root + "/v1/abort"
    try:
        requests.post(abort_url, timeout=3)
    except Exception:
        try:
            requests.get(abort_url, timeout=3)
        except Exception:
            pass


def iter_sse_chat(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    connect_timeout: float,
    read_timeout: float,
    session: requests.Session | None = None,
) -> Iterator[str]:
    """Yield content deltas from OpenAI-compatible SSE stream."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    http = session or requests
    with http.post(
        url,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=(connect_timeout, read_timeout),
        stream=True,
    ) as r:
        if r.status_code == 503:
            raise RuntimeError("板上 RKLLM 正忙（503），稍后再试")
        if r.status_code >= 400:
            body = r.text[:500] if r.text else ""
            raise RuntimeError(f"HTTP {r.status_code}: {body}")

        # SSE often omits charset; requests would otherwise decode as ISO-8859-1
        # and turn UTF-8 Chinese into mojibake (e.g. 你好 → ä½ å¥½).
        r.encoding = "utf-8"

        for raw in r.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            if isinstance(raw, bytes):
                line = raw.decode("utf-8", errors="replace").strip()
            else:
                line = raw.strip()
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str) and content:
                yield content


def chat_once_stream_with_wait(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    connect_timeout: float,
    read_timeout: float,
) -> str:
    """SSE 逐字打印；首 token 前显示计时 spinner。Ctrl+C 打断。"""
    import queue
    import threading

    q: queue.Queue = queue.Queue()
    err: list[BaseException] = []
    session = requests.Session()

    def worker() -> None:
        try:
            for piece in iter_sse_chat(
                base_url,
                model,
                messages,
                connect_timeout,
                read_timeout,
                session=session,
            ):
                q.put(("tok", piece))
            q.put(("done", None))
        except BaseException as e:
            err.append(e)
            q.put(("err", None))

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    prefix = f"{Style.GREEN}{Style.BOLD}Qwen3> {Style.RESET}" if _USE_COLOR else "Qwen3> "
    spinner = "|/-\\"
    spin_i = 0
    started = time.time()
    first = True
    full_parts: list[str] = []

    try:
        while True:
            try:
                kind, payload = q.get(timeout=0.1)
            except queue.Empty:
                if first:
                    elapsed = time.time() - started
                    ch = spinner[spin_i % len(spinner)]
                    spin_i += 1
                    msg = f"Qwen3> {ch} 推理中... {elapsed:.1f}s（Ctrl+C 打断）"
                    print(
                        f"\r{Style.DIM}{Style.YELLOW}{msg}{Style.RESET}",
                        end="",
                        flush=True,
                    )
                continue

            if kind == "err":
                print("\r" + " " * 64 + "\r", end="", flush=True)
                raise err[0]
            if kind == "done":
                break

            if first:
                print("\r" + " " * 64 + "\r", end="", flush=True)
                print(prefix, end="", flush=True)
                first = False
            print(payload, end="", flush=True)
            full_parts.append(payload)
    except KeyboardInterrupt:
        print("\r" + " " * 64 + "\r", end="", flush=True)
        if not first:
            print(flush=True)
        try:
            session.close()
        except Exception:
            pass
        request_abort(base_url)
        raise GenerationInterrupted() from None
    finally:
        try:
            session.close()
        except Exception:
            pass

    t.join(timeout=1)
    if first:
        print("\r" + " " * 64 + "\r", end="", flush=True)
        cprint("Qwen3> (空响应)", Style.YELLOW)
        return ""
    print(flush=True)
    return "".join(full_parts)


def read_user_line() -> str:
    if _USE_COLOR:
        return pt_prompt(HTML("<ansicyan><b>你&gt;</b></ansicyan> ")).strip()
    return pt_prompt("你> ").strip()


def print_help() -> None:
    cprint("命令:", Style.BOLD, Style.BLUE)
    print(
        f"  {Style.CYAN}/help{Style.RESET}     显示帮助\n"
        f"  {Style.CYAN}/clear{Style.RESET}    清空对话历史\n"
        f"  {Style.CYAN}/quit{Style.RESET}     退出\n"
        f"  {Style.CYAN}Ctrl+C{Style.RESET}   生成中打断；在输入提示符再按一次退出\n"
        "直接输入中文即可与板上 Qwen3 对话（SSE 逐字输出，无工具调用）。"
    )


def trim_history(messages: list[dict[str, str]], max_n: int) -> None:
    while len(messages) > max_n:
        messages.pop(0)
    if messages and messages[0].get("role") != "user":
        messages.pop(0)


def main() -> int:
    parser = argparse.ArgumentParser(description="RK3588 Qwen3 直连中文命令行客户端")
    parser.add_argument("--base-url", default=config.BASE_URL)
    parser.add_argument("--model", default=config.MODEL)
    parser.add_argument("--connect-timeout", type=float, default=config.CONNECT_TIMEOUT)
    parser.add_argument("--read-timeout", type=float, default=config.READ_TIMEOUT)
    args = parser.parse_args()

    cprint(f"检查板上服务 {args.base_url} ...", Style.DIM)
    try:
        models = check_server(args.base_url, args.connect_timeout)
        ids = [m.get("id") for m in (models.get("data") or []) if isinstance(m, dict)]
        cprint(f"已连接。模型: {', '.join(ids) if ids else args.model}", Style.GREEN)
    except Exception as e:
        cprint(f"无法连接 RKLLM 服务: {e}", Style.RED, Style.BOLD)
        cprint(
            "请确认板上 rkllm-server 已启动，且模型已放到 /opt/models/：\n"
            "  ssh root@192.168.1.14 'systemctl status rkllm-server'\n"
            "  curl -sS http://192.168.1.14:8080/v1/models",
            Style.YELLOW,
        )
        return 1

    print_help()
    cprint("-" * 40, Style.DIM)

    history: list[dict[str, str]] = []

    while True:
        try:
            user_text = read_user_line()
        except (EOFError, KeyboardInterrupt):
            print()
            user_text = "/quit"

        if not user_text:
            continue
        if user_text in ("/quit", "/exit", "exit", "quit"):
            cprint("已退出。", Style.DIM)
            break
        if user_text == "/help":
            print_help()
            continue
        if user_text == "/clear":
            history = []
            cprint("已清空对话历史。", Style.GREEN)
            continue

        history.append({"role": "user", "content": user_text})
        trim_history(history, config.MAX_HISTORY)

        try:
            reply = chat_once_stream_with_wait(
                args.base_url,
                args.model,
                history,
                args.connect_timeout,
                args.read_timeout,
            )
        except GenerationInterrupted:
            if history and history[-1].get("role") == "user":
                history.pop()
            cprint("（已打断，可继续提问）", Style.YELLOW)
            continue
        except Exception as e:
            history.pop()  # 撤回失败的本轮 user
            cprint(f"Qwen3> 错误: {e}", Style.RED, Style.BOLD)
            continue

        history.append({"role": "assistant", "content": reply})
        trim_history(history, config.MAX_HISTORY)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
