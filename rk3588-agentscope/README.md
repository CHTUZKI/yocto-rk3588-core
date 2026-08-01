# rk3588-agentscope

板端 AgentScope 2.0 项目：使用 AgentScope `ReActAgent` 对接本机 RKLLM 的 Qwen3 OpenAI 兼容接口。

## 设计

- Qwen3 RKLLM：`http://127.0.0.1:8080/v1`
- AgentScope：板端 Python 进程
- 默认 workspace：`/tmp/qwen-agent-workspace`
- 工具：安全的文件读写、Python 文件执行、单条系统命令
- 不使用交互式 `vi`，避免 Agent 生成 shell 重定向和多步命令

## 当前状态

项目代码、AgentScope 2.0.5 aarch64 vendor 打包脚本和 Yocto recipe 已准备好。构建前需要生成：

```bash
./scripts/fetch-agentscope-aarch64.sh
```

输出：

```text
deploy/vendor/agentscope-aarch64-site.tar.gz
```

生成 vendor 包后，`agentscope-board` 已加入 `packagegroup-rk3588-llm`，会随下一次镜像构建进入 `/opt/agentscope`。

## PC/板端开发测试

```bash
cd rk3588-agentscope
./run.sh
```

可覆盖配置：

```bash
AGENTSCOPE_MODEL_SERVER=http://127.0.0.1:8080/v1 \
AGENTSCOPE_WORKSPACE=/tmp/qwen-agent-workspace \
./run.sh
```

示例任务：

```text
用 Python 写一个 99 乘法表，保存并运行
```

AgentScope 应调用 `write_text_file` 和 `run_python_file`，而不是返回伪造的运行结果。
