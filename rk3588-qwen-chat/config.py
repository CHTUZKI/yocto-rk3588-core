# 本机（PC/WSL）客户端：直连板上 RKLLM OpenAI 兼容 HTTP 服务
# 不经过 Qwen-Agent / SSH 工具链

BASE_URL = "http://192.168.1.14:8080/v1"
MODEL = "Qwen3-4B"

# 请求超时（秒）。板上推理可能较慢。
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 600

# 多轮对话保留的消息条数（user+assistant 合计）
MAX_HISTORY = 20
