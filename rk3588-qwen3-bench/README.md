# rk3588-qwen3-bench

PC/WSL 端的 Qwen3 RKLLM 性能测试工具，直连板端 OpenAI 兼容接口，不经过 SSH Agent。

## 测试指标

- TTFT：首个非空输出块延迟
- wall：整轮 HTTP 请求耗时
- Prefill：服务端 RKLLM prompt 处理速度
- Generate：服务端 RKLLM token 生成速度
- 生成 token 数
- RKLLM 内存峰值

## 使用

```bash
cd rk3588-qwen3-bench
./run.sh
```

正式测试 3 次、预热 1 次，限制生成 256 token：

```bash
./run.sh --warmup 1 --runs 3 --max-tokens 256
```

启用 Qwen3 思考模式对比：

```bash
./run.sh --thinking --max-tokens 512
```

自定义 prompt 或输出 JSON：

```bash
./run.sh --prompt '写一个最小的 C hello world' --json
```

测试前需要确认板端服务已运行：

```bash
curl -sS http://192.168.1.14:8080/v1/models
```
