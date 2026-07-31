# 本机（PC/WSL）客户端配置：通过 SSH 连接开发板
# 当前板上 openssh 允许空密码登录（Yocto debug-tweaks）
HOST = "192.168.1.14"
PORT = 22
USER = "root"
PASSWORD = ""  # 空密码；若你改过密码，填到这里

# 板上路径
REMOTE_AGENT = "/opt/qwen_agent/qwen_agent_onboard.py"
REMOTE_SESSION = "/opt/qwen_agent/agent_session.py"
REMOTE_SERVER_DIR = "/opt/rkllm_server"
REMOTE_MODEL = "/opt/models/Qwen3-4B-Instruct-2507-w8a8-rk3588.rkllm"

# 连接超时（秒）
CONNECT_TIMEOUT = 15
