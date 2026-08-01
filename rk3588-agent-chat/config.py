# 本机（PC/WSL）客户端配置：通过 SSH 连接开发板
# 使用 RK3588_PASSWORD 传入密码，避免把凭据写入仓库；空字符串适用于 debug-tweaks。
import os

HOST = "192.168.1.14"
PORT = 22
USER = "root"
PASSWORD = os.environ.get("RK3588_PASSWORD", "")

# 板上路径
REMOTE_AGENT = "/opt/qwen_agent/qwen_agent_onboard.py"
REMOTE_SESSION = "/opt/qwen_agent/agent_session.py"
REMOTE_SERVER_DIR = "/opt/rkllm_server"
# Empty means auto-detect: prefer eMMC, then fall back to the USB drive.
REMOTE_MODEL = os.environ.get("RK3588_REMOTE_MODEL", "")

# 连接超时（秒）
CONNECT_TIMEOUT = 15
