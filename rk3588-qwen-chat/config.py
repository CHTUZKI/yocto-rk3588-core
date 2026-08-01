# 本机（PC/WSL）客户端：直连板上 RKLLM OpenAI 兼容 HTTP 服务
# 不经过 Qwen-Agent / SSH 工具链

BASE_URL = "http://192.168.1.14:8080/v1"
MODEL = "Qwen2.5-Coder-3B"

# 请求超时（秒）。服务端已限制单次生成，首 token 正常应很快到达。
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 180

# RKLLM 在初始化时固定最大生成长度；客户端也显式发送该值，避免配置漂移。
MAX_TOKENS = 512

# 保留较短上下文可明显降低 prefill 延迟和 KV/cache 压力。
MAX_HISTORY = 8
MAX_HISTORY_CHARS = 12000

# 关闭 Qwen2.5 的思考模式，适合板端代码问答的低延迟交互。
ENABLE_THINKING = False
