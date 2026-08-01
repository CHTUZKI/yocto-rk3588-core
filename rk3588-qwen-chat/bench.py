#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测板上 RKLLM 推理速度（直连 HTTP，不走 Agent）。

输出：
  - TTFT：首 token 延迟
  - Client decode tok/s：按 SSE content 块数估算（约等于 token）
  - Server RKLLM：若 flask_server 已上报 usage.rkllm，则打印官方 prefill/generate tok/s

用法:
  cd rk3588-qwen-chat && ./bench.sh
  ./bench.sh --runs 3 --max-tokens 256
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from typing import Any

try:
    import requests
except ImportError:
    print("缺少 requests，请先：./bench.sh 或 pip install -r requirements.txt")
    raise SystemExit(1)

import config


def check_server(base_url: str, timeout: float) -> str:
    url = base_url.rstrip("/") + "/models"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    models = data.get("data") or []
    if models:
        return str(models[0].get("id") or config.MODEL)
    return config.MODEL


def run_once(
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    connect_timeout: float,
    read_timeout: float,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max_tokens,
        "enable_thinking": False,
    }

    t0 = time.perf_counter()
    t_first: float | None = None
    chunks = 0
    chars = 0
    usage: dict[str, Any] | None = None
    preview_parts: list[str] = []

    with requests.post(
        url,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=(connect_timeout, read_timeout),
        stream=True,
    ) as r:
        if r.status_code == 503:
            raise RuntimeError("板上 RKLLM 正忙（503）")
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
        r.encoding = "utf-8"

        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(obj.get("usage"), dict):
                usage = obj["usage"]
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if not isinstance(content, str) or not content:
                continue
            if t_first is None:
                t_first = time.perf_counter()
            chunks += 1
            chars += len(content)
            if len(preview_parts) < 40:
                preview_parts.append(content)

    t1 = time.perf_counter()
    ttft = (t_first - t0) if t_first is not None else None
    gen_s = (t1 - t_first) if t_first is not None else None
    client_tps = (chunks / gen_s) if gen_s and gen_s > 0 else None

    rkllm = (usage or {}).get("rkllm") if usage else None
    return {
        "ttft_s": ttft,
        "wall_s": t1 - t0,
        "chunks": chunks,
        "chars": chars,
        "client_decode_tps": client_tps,
        "usage": usage,
        "rkllm": rkllm,
        "preview": "".join(preview_parts),
    }


def _fmt(v: float | None, unit: str = "", digits: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{digits}f}{unit}"


def main() -> int:
    parser = argparse.ArgumentParser(description="RK3588 RKLLM token 速度基准测试")
    parser.add_argument("--base-url", default=config.BASE_URL)
    parser.add_argument("--model", default=config.MODEL)
    parser.add_argument("--runs", type=int, default=3, help="正式测速次数（不含 warmup）")
    parser.add_argument("--warmup", type=int, default=1, help="预热次数（不计入统计）")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument(
        "--prompt",
        default="用中文写一段约200字的嵌入式 Linux 开发介绍，不要列表，不要调用工具。",
    )
    args = parser.parse_args()

    print(f"检查服务 {args.base_url} ...")
    try:
        mid = check_server(args.base_url, config.CONNECT_TIMEOUT)
    except Exception as e:
        print(f"无法连接板上 RKLLM: {e}")
        return 1
    model = args.model or mid
    print(f"模型: {model}")
    print(f"warmup={args.warmup}, runs={args.runs}, max_tokens={args.max_tokens}")
    print("-" * 56)

    total = args.warmup + args.runs
    results: list[dict[str, Any]] = []

    for i in range(total):
        tag = "warmup" if i < args.warmup else f"run {i - args.warmup + 1}/{args.runs}"
        print(f"[{tag}] 请求中...", flush=True)
        try:
            r = run_once(
                args.base_url,
                model,
                args.prompt,
                args.max_tokens,
                config.CONNECT_TIMEOUT,
                config.READ_TIMEOUT,
            )
        except Exception as e:
            print(f"  失败: {e}")
            if i < args.warmup:
                continue
            return 1

        rk = r.get("rkllm") or {}
        print(
            f"  TTFT={_fmt(r['ttft_s'], 's', 3)}  "
            f"wall={_fmt(r['wall_s'], 's', 2)}  "
            f"chunks≈{r['chunks']}  chars={r['chars']}"
        )
        print(f"  client decode≈{_fmt(r['client_decode_tps'], ' tok/s', 1)}")
        if rk:
            print(
                f"  server prefill={_fmt(rk.get('prefill_tokens_per_sec'), ' tok/s', 1)}  "
                f"generate={_fmt(rk.get('generate_tokens_per_sec'), ' tok/s', 1)}  "
                f"(prefill {rk.get('prefill_tokens')} tok / {rk.get('prefill_time_ms')} ms, "
                f"gen {rk.get('generate_tokens')} tok / {rk.get('generate_time_ms')} ms)"
            )
        else:
            print("  server RKLLM: 未返回 usage.rkllm（请更新并重启板上 flask_server.py）")
        if r.get("preview"):
            prev = r["preview"].replace("\n", " ")
            if len(prev) > 80:
                prev = prev[:80] + "..."
            print(f"  preview: {prev}")

        if i >= args.warmup:
            results.append(r)

    if not results:
        print("无有效测速结果")
        return 1

    print("-" * 56)
    print("汇总（正式 runs）:")
    ttfts = [x["ttft_s"] for x in results if x["ttft_s"] is not None]
    ctps = [x["client_decode_tps"] for x in results if x["client_decode_tps"] is not None]
    stps = [
        (x.get("rkllm") or {}).get("generate_tokens_per_sec")
        for x in results
        if (x.get("rkllm") or {}).get("generate_tokens_per_sec") is not None
    ]
    ptps = [
        (x.get("rkllm") or {}).get("prefill_tokens_per_sec")
        for x in results
        if (x.get("rkllm") or {}).get("prefill_tokens_per_sec") is not None
    ]

    def avg(xs: list[float]) -> float | None:
        return statistics.mean(xs) if xs else None

    print(f"  TTFT avg:            {_fmt(avg(ttfts), 's', 3)}")
    print(f"  client decode avg:   {_fmt(avg(ctps), ' tok/s', 1)}")
    print(f"  server generate avg: {_fmt(avg(stps), ' tok/s', 1)}")
    print(f"  server prefill avg:  {_fmt(avg(ptps), ' tok/s', 1)}")
    print("说明: generate tok/s 是生成速度；prefill 是吃 prompt 的速度。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
