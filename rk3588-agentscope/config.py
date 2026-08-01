import os

MODEL_SERVER = os.environ.get("AGENTSCOPE_MODEL_SERVER", "http://127.0.0.1:8080/v1")
MODEL = os.environ.get("AGENTSCOPE_MODEL", "Qwen3-4B")
API_KEY = os.environ.get("AGENTSCOPE_API_KEY", "EMPTY")
WORKSPACE = os.environ.get("AGENTSCOPE_WORKSPACE", "/tmp/qwen-agent-workspace")
MAX_TOKENS = int(os.environ.get("AGENTSCOPE_MAX_TOKENS", "512"))
ENABLE_THINKING = os.environ.get("AGENTSCOPE_ENABLE_THINKING", "0") == "1"
