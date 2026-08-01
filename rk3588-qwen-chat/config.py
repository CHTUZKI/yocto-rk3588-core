# 本机（PC/WSL）客户端：直连板上 RKLLM OpenAI 兼容 HTTP 服务
# 不经过 Qwen-Agent / SSH 工具链

BASE_URL = "http://192.168.1.14:8080/v1"
MODEL = "Qwen3-4B"

# 服务端已限制单次生成，首 token 正常应较快到达。
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 180

# Qwen3 低延迟默认值；可用 --thinking 显式打开思考模式。
MAX_TOKENS = 512
ENABLE_THINKING = False

# 控制 prefill 延迟和 4K context 内的历史膨胀。
MAX_HISTORY = 8
MAX_HISTORY_CHARS = 12000
