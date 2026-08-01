#!/usr/bin/env python3
"""Measure Qwen3 RKLLM TTFT, prefill and generation speed over HTTP SSE."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any

import requests

import config


def check_server(base_url: str, timeout: float) -> str:
    response = requests.get(base_url.rstrip("/") + "/models", timeout=timeout)
    response.raise_for_status()
    models = response.json().get("data") or []
    return str(models[0].get("id") if models else config.MODEL)


def run_once(
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    enable_thinking: bool,
    connect_timeout: float,
    read_timeout: float,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max_tokens,
        "enable_thinking": enable_thinking,
    }
    started = time.perf_counter()
    first_token_at: float | None = None
    chunks = 0
    chars = 0
    usage: dict[str, Any] | None = None

    with requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(connect_timeout, read_timeout),
        stream=True,
    ) as response:
        if response.status_code == 503:
            raise RuntimeError("板上 RKLLM 正忙（503）")
        response.raise_for_status()
        response.encoding = "utf-8"
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            content = (choices[0].get("delta") or {}).get("content")
            if isinstance(content, str) and content:
                first_token_at = first_token_at or time.perf_counter()
                chunks += 1
                chars += len(content)

    finished = time.perf_counter()
    ttft = first_token_at - started if first_token_at else None
    generation_time = finished - first_token_at if first_token_at else None
    rkllm = (usage or {}).get("rkllm") or {}
    generated_tokens = rkllm.get("generate_tokens")
    client_tps = (
        float(generated_tokens) / generation_time
        if generated_tokens and generation_time and generation_time > 0
        else None
    )
    return {
        "ttft_s": ttft,
        "wall_s": finished - started,
        "generation_s": generation_time,
        "chunks": chunks,
        "chars": chars,
        "usage": usage,
        "client_tps": client_tps,
        "server_prefill_tps": rkllm.get("prefill_tokens_per_sec"),
        "server_generate_tps": rkllm.get("generate_tokens_per_sec"),
        "prompt_tokens": rkllm.get("prefill_tokens"),
        "generate_tokens": generated_tokens,
        "memory_mb": rkllm.get("memory_usage_mb"),
    }


def fmt(value: Any, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}{suffix}"


def average(results: list[dict[str, Any]], key: str) -> float | None:
    values = [float(item[key]) for item in results if item.get(key) is not None]
    return statistics.mean(values) if values else None


def main() -> int:
    parser = argparse.ArgumentParser(description="RK3588 Qwen3 token 性能测试")
    parser.add_argument("--base-url", default=config.BASE_URL)
    parser.add_argument("--model", default=config.MODEL)
    parser.add_argument("--prompt", default=config.PROMPT)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=config.MAX_TOKENS)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.runs < 1 or args.warmup < 0:
        parser.error("--runs 必须大于 0，--warmup 不能为负数")
    max_tokens = max(1, min(args.max_tokens, 768))
    thinking = config.ENABLE_THINKING or args.thinking

    try:
        model = args.model or check_server(args.base_url, config.CONNECT_TIMEOUT)
        check_server(args.base_url, config.CONNECT_TIMEOUT)
    except Exception as exc:
        print(f"无法连接 {args.base_url}: {exc}")
        return 1

    results: list[dict[str, Any]] = []
    total = args.warmup + args.runs
    for index in range(total):
        label = "warmup" if index < args.warmup else f"run {index - args.warmup + 1}/{args.runs}"
        print(f"[{label}] model={model} max_tokens={max_tokens} thinking={thinking}", flush=True)
        try:
            result = run_once(
                args.base_url,
                model,
                args.prompt,
                max_tokens,
                thinking,
                config.CONNECT_TIMEOUT,
                config.READ_TIMEOUT,
            )
        except Exception as exc:
            print(f"  失败: {exc}")
            if index < args.warmup:
                continue
            return 1
        if index >= args.warmup:
            results.append(result)
        print(
            "  TTFT=%s  wall=%s  prefill=%s tok/s  generate=%s tok/s  tokens=%s  mem=%s MB"
            % (
                fmt(result["ttft_s"], "s", 3),
                fmt(result["wall_s"], "s"),
                fmt(result["server_prefill_tps"], " tok/s", 1),
                fmt(result["server_generate_tps"], " tok/s", 1),
                result.get("generate_tokens", "n/a"),
                fmt(result.get("memory_mb"), "", 0),
            )
        )
        if result.get("usage") is None:
            print("  警告：服务端没有返回 usage.rkllm，请确认已更新 Qwen3 服务")

    print("-" * 72)
    print("平均值（正式测试）")
    for key, label, suffix, digits in (
        ("ttft_s", "TTFT", "s", 3),
        ("wall_s", "总耗时", "s", 2),
        ("server_prefill_tps", "Prefill", " tok/s", 1),
        ("server_generate_tps", "Generate", " tok/s", 1),
        ("memory_mb", "内存峰值", " MB", 0),
    ):
        print(f"{label:12}: {fmt(average(results, key), suffix, digits)}")

    if args.as_json:
        print(json.dumps({"config": vars(args), "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
