import ctypes
import sys
import os
import subprocess
import resource
import threading
import time
import argparse
import json
from flask import Flask, request, jsonify, Response
import re

app = Flask(__name__)

# Load librkllmrt: prefer /opt/rkllm (image layout), else local lib/ (dev SCP layout)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_lib_candidates = (
    "/opt/rkllm/librkllmrt.so",
    os.path.join(_SCRIPT_DIR, "lib", "librkllmrt.so"),
)
for _lib_path in _lib_candidates:
    if os.path.isfile(_lib_path):
        rkllm_lib = ctypes.CDLL(_lib_path)
        break
else:
    raise FileNotFoundError(
        "librkllmrt.so not found in /opt/rkllm or %s/lib" % _SCRIPT_DIR
    )
# Define the structures from the library
RKLLM_Handle_t = ctypes.c_void_p
userdata = ctypes.c_void_p(None)

LLMCallState = ctypes.c_int
LLMCallState.RKLLM_RUN_NORMAL  = 0
LLMCallState.RKLLM_RUN_WAITING  = 1
LLMCallState.RKLLM_RUN_FINISH  = 2
LLMCallState.RKLLM_RUN_ERROR   = 3

RKLLMInputType = ctypes.c_int
RKLLMInputType.RKLLM_INPUT_PROMPT      = 0
RKLLMInputType.RKLLM_INPUT_TOKEN       = 1
RKLLMInputType.RKLLM_INPUT_EMBED       = 2
RKLLMInputType.RKLLM_INPUT_MULTIMODAL  = 3

RKLLMInferMode = ctypes.c_int
RKLLMInferMode.RKLLM_INFER_GENERATE = 0
RKLLMInferMode.RKLLM_INFER_GET_LAST_HIDDEN_LAYER = 1
RKLLMInferMode.RKLLM_INFER_GET_LOGITS = 2
class RKLLMExtendParam(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("embed_flash", ctypes.c_int8),
        ("enabled_cpus_num", ctypes.c_int8),
        ("enabled_cpus_mask", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint8),
        ("use_cross_attn", ctypes.c_int8),
        ("reserved", ctypes.c_uint8 * 104)
    ]

class RKLLMParam(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("max_context_len", ctypes.c_int32),
        ("max_new_tokens", ctypes.c_int32),
        ("top_k", ctypes.c_int32),
        ("n_keep", ctypes.c_int32),
        ("top_p", ctypes.c_float),
        ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float),
        ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float),
        ("mirostat", ctypes.c_int32),
        ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
        ("skip_special_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("img_start", ctypes.c_char_p),
        ("img_end", ctypes.c_char_p),
        ("img_content", ctypes.c_char_p),
        ("extend_param", RKLLMExtendParam),
    ]

class RKLLMLoraAdapter(ctypes.Structure):
    _fields_ = [
        ("lora_adapter_path", ctypes.c_char_p),
        ("lora_adapter_name", ctypes.c_char_p),
        ("scale", ctypes.c_float)
    ]

class RKLLMEmbedInput(ctypes.Structure):
    _fields_ = [
        ("embed", ctypes.POINTER(ctypes.c_float)),
        ("n_tokens", ctypes.c_size_t)
    ]

class RKLLMTokenInput(ctypes.Structure):
    _fields_ = [
        ("input_ids", ctypes.POINTER(ctypes.c_int32)),
        ("n_tokens", ctypes.c_size_t)
    ]

class RKLLMMultiModalInput(ctypes.Structure):
    _fields_ = [
        ("prompt", ctypes.c_char_p),
        ("image_embed", ctypes.POINTER(ctypes.c_float)),
        ("n_image_tokens", ctypes.c_size_t),
        ("n_image", ctypes.c_size_t),
        ("image_width", ctypes.c_size_t),
        ("image_height", ctypes.c_size_t)
    ]

class RKLLMInputUnion(ctypes.Union):
    _fields_ = [
        ("prompt_input", ctypes.c_char_p),
        ("embed_input", RKLLMEmbedInput),
        ("token_input", RKLLMTokenInput),
        ("multimodal_input", RKLLMMultiModalInput)
    ]

class RKLLMInput(ctypes.Structure):
    _fields_ = [
        ("role", ctypes.c_char_p),
        ("enable_thinking", ctypes.c_bool),
        ("input_type", RKLLMInputType),
        ("input_data", RKLLMInputUnion)
    ]

class RKLLMLoraParam(ctypes.Structure):
    _fields_ = [
        ("lora_adapter_name", ctypes.c_char_p)
    ]

class RKLLMPromptCacheParam(ctypes.Structure):
    _fields_ = [
        ("save_prompt_cache", ctypes.c_int),
        ("prompt_cache_path", ctypes.c_char_p)
    ]

class RKLLMInferParam(ctypes.Structure):
    _fields_ = [
        ("mode", RKLLMInferMode),
        ("lora_params", ctypes.POINTER(RKLLMLoraParam)),
        ("prompt_cache_params", ctypes.POINTER(RKLLMPromptCacheParam)),
        ("keep_history", ctypes.c_int)
    ]

class RKLLMResultLastHiddenLayer(ctypes.Structure):
    _fields_ = [
        ("hidden_states", ctypes.POINTER(ctypes.c_float)),
        ("embd_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int)
    ]

class RKLLMResultLogits(ctypes.Structure):
    _fields_ = [
        ("logits", ctypes.POINTER(ctypes.c_float)),
        ("vocab_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int)
    ]

class RKLLMPerfStat(ctypes.Structure):
    _fields_ = [
        ("prefill_time_ms", ctypes.c_float),
        ("prefill_tokens", ctypes.c_int),
        ("generate_time_ms", ctypes.c_float),
        ("generate_tokens", ctypes.c_int),
        ("memory_usage_mb", ctypes.c_float)
    ]

class RKLLMResult(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
        ("logits", RKLLMResultLogits),
        ("perf", RKLLMPerfStat)
    ]

# Create a lock to control multi-user access to the server.
lock = threading.Lock()

# Create a global variable to indicate whether the server is currently in a blocked state.
is_blocking = False

# Define global variables to store the callback function output for displaying in the Gradio interface
system_prompt = ''
global_text = []
global_state = -1
split_byte_data = bytes(b"") # Used to store the segmented byte data
# Last RKLLM PerfStat captured from callback (filled on FINISH / last NORMAL).
global_last_perf = None

recevied_messages = []


def _capture_perf(result):
    """Copy RKLLM PerfStat into global_last_perf when fields look valid."""
    global global_last_perf
    try:
        p = result.contents.perf
        prefill_ms = float(p.prefill_time_ms)
        generate_ms = float(p.generate_time_ms)
        prefill_tokens = int(p.prefill_tokens)
        generate_tokens = int(p.generate_tokens)
        memory_mb = float(p.memory_usage_mb)
    except Exception:
        return
    if prefill_ms <= 0 and generate_ms <= 0 and generate_tokens <= 0 and prefill_tokens <= 0:
        return
    global_last_perf = {
        "prefill_time_ms": prefill_ms,
        "prefill_tokens": prefill_tokens,
        "generate_time_ms": generate_ms,
        "generate_tokens": generate_tokens,
        "memory_usage_mb": memory_mb,
    }


def _print_perf(perf):
    if not perf:
        return
    prefill_ms = perf.get("prefill_time_ms") or 0.0
    generate_ms = perf.get("generate_time_ms") or 0.0
    prefill_tok = perf.get("prefill_tokens") or 0
    generate_tok = perf.get("generate_tokens") or 0
    mem = perf.get("memory_usage_mb") or 0.0
    prefill_tps = (prefill_tok / (prefill_ms / 1000.0)) if prefill_ms > 0 else 0.0
    generate_tps = (generate_tok / (generate_ms / 1000.0)) if generate_ms > 0 else 0.0
    print(
        "[RKLLM perf] "
        f"prefill={prefill_tok} tok / {prefill_ms:.1f} ms ({prefill_tps:.1f} tok/s) | "
        f"generate={generate_tok} tok / {generate_ms:.1f} ms ({generate_tps:.1f} tok/s) | "
        f"mem={mem:.1f} MB",
        flush=True,
    )


def _usage_from_perf(perf):
    """OpenAI-compatible usage + RKLLM extended fields for clients/bench."""
    if not perf:
        return {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
    prompt = int(perf.get("prefill_tokens") or 0)
    completion = int(perf.get("generate_tokens") or 0)
    prefill_ms = float(perf.get("prefill_time_ms") or 0.0)
    generate_ms = float(perf.get("generate_time_ms") or 0.0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "rkllm": {
            "prefill_time_ms": prefill_ms,
            "prefill_tokens": prompt,
            "prefill_tokens_per_sec": (prompt / (prefill_ms / 1000.0)) if prefill_ms > 0 else None,
            "generate_time_ms": generate_ms,
            "generate_tokens": completion,
            "generate_tokens_per_sec": (completion / (generate_ms / 1000.0)) if generate_ms > 0 else None,
            "memory_usage_mb": float(perf.get("memory_usage_mb") or 0.0),
        },
    }


# Define the callback function
def callback_impl(result, userdata, state):
    global global_text, global_state, split_byte_data
    if state == LLMCallState.RKLLM_RUN_FINISH:
        global_state = state
        _capture_perf(result)
        print("\n", flush=True)
        _print_perf(global_last_perf)
    elif state == LLMCallState.RKLLM_RUN_ERROR:
        global_state = state
        print("run error", flush=True)
    elif state == LLMCallState.RKLLM_RUN_NORMAL:
        global_state = state
        _capture_perf(result)
        # Append whole token/chunk strings (not char-extend) for stream consumers.
        text = result.contents.text.decode('utf-8')
        if text:
            global_text.append(text)
            print(text, end='', flush=True)
    return 0
    

# Connect the callback function between the Python side and the C++ side
callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int)
callback = callback_type(callback_impl)

# Define the RKLLM class, which includes initialization, inference, and release operations for the RKLLM model in the dynamic library
class RKLLM(object):
    def __init__(self, model_path, lora_model_path = None, prompt_cache_path = None, platform = "rk3588"):
        rkllm_param = RKLLMParam()
        rkllm_param.model_path = bytes(model_path, 'utf-8')

        rkllm_param.max_context_len = 4096
        rkllm_param.max_new_tokens = 4096
        rkllm_param.skip_special_token = True
        rkllm_param.n_keep = -1
        rkllm_param.top_k = 1
        rkllm_param.top_p = 0.9
        rkllm_param.temperature = 0.8
        rkllm_param.repeat_penalty = 1.1
        rkllm_param.frequency_penalty = 0.0
        rkllm_param.presence_penalty = 0.0

        rkllm_param.mirostat = 0
        rkllm_param.mirostat_tau = 5.0
        rkllm_param.mirostat_eta = 0.1

        rkllm_param.is_async = False

        rkllm_param.img_start = "".encode('utf-8')
        rkllm_param.img_end = "".encode('utf-8')
        rkllm_param.img_content = "".encode('utf-8')

        rkllm_param.extend_param.base_domain_id = 0
        rkllm_param.extend_param.embed_flash = 1
        rkllm_param.extend_param.n_batch = 1
        rkllm_param.extend_param.use_cross_attn = 0
        rkllm_param.extend_param.enabled_cpus_num = 4
        if platform.lower() in ["rk3576", "rk3588"]:
            rkllm_param.extend_param.enabled_cpus_mask = (1 << 4)|(1 << 5)|(1 << 6)|(1 << 7)
        else:
            rkllm_param.extend_param.enabled_cpus_mask = (1 << 0)|(1 << 1)|(1 << 2)|(1 << 3)

        self.handle = RKLLM_Handle_t()

        self.rkllm_init = rkllm_lib.rkllm_init
        self.rkllm_init.argtypes = [ctypes.POINTER(RKLLM_Handle_t), ctypes.POINTER(RKLLMParam), callback_type]
        self.rkllm_init.restype = ctypes.c_int
        ret = self.rkllm_init(ctypes.byref(self.handle), ctypes.byref(rkllm_param), callback)
        if (ret != 0):
            print("\nrkllm init failed\n")
            exit(0)
        else:
            print("\nrkllm init success!\n")

        self.rkllm_run = rkllm_lib.rkllm_run
        self.rkllm_run.argtypes = [RKLLM_Handle_t, ctypes.POINTER(RKLLMInput), ctypes.POINTER(RKLLMInferParam), ctypes.c_void_p]
        self.rkllm_run.restype = ctypes.c_int
        
        self.set_chat_template = rkllm_lib.rkllm_set_chat_template
        self.set_chat_template.argtypes = [RKLLM_Handle_t, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        self.set_chat_template.restype = ctypes.c_int
        
        self.set_function_tools_ = rkllm_lib.rkllm_set_function_tools
        self.set_function_tools_.argtypes = [RKLLM_Handle_t, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        self.set_function_tools_.restype = ctypes.c_int
        
        # system_prompt = "<|im_start|>system You are a helpful assistant. <|im_end|>"
        # prompt_prefix = "<|im_start|>user"
        # prompt_postfix = "<|im_end|><|im_start|>assistant"
        # self.set_chat_template(self.handle, ctypes.c_char_p(system_prompt.encode('utf-8')), ctypes.c_char_p(prompt_prefix.encode('utf-8')), ctypes.c_char_p(prompt_postfix.encode('utf-8')))

        self.rkllm_destroy = rkllm_lib.rkllm_destroy
        self.rkllm_destroy.argtypes = [RKLLM_Handle_t]
        self.rkllm_destroy.restype = ctypes.c_int
        
        self.rkllm_abort = rkllm_lib.rkllm_abort

        rkllm_lora_params = None
        if lora_model_path:
            lora_adapter_name = "test"
            lora_adapter = RKLLMLoraAdapter()
            ctypes.memset(ctypes.byref(lora_adapter), 0, ctypes.sizeof(RKLLMLoraAdapter))
            lora_adapter.lora_adapter_path = ctypes.c_char_p((lora_model_path).encode('utf-8'))
            lora_adapter.lora_adapter_name = ctypes.c_char_p((lora_adapter_name).encode('utf-8'))
            lora_adapter.scale = 1.0

            rkllm_load_lora = rkllm_lib.rkllm_load_lora
            rkllm_load_lora.argtypes = [RKLLM_Handle_t, ctypes.POINTER(RKLLMLoraAdapter)]
            rkllm_load_lora.restype = ctypes.c_int
            rkllm_load_lora(self.handle, ctypes.byref(lora_adapter))
            rkllm_lora_params = RKLLMLoraParam()
            rkllm_lora_params.lora_adapter_name = ctypes.c_char_p((lora_adapter_name).encode('utf-8'))
        
        self.rkllm_infer_params = RKLLMInferParam()
        ctypes.memset(ctypes.byref(self.rkllm_infer_params), 0, ctypes.sizeof(RKLLMInferParam))
        self.rkllm_infer_params.mode = RKLLMInferMode.RKLLM_INFER_GENERATE
        self.rkllm_infer_params.lora_params = ctypes.pointer(rkllm_lora_params) if rkllm_lora_params else None
        self.rkllm_infer_params.keep_history = 0

        self.prompt_cache_path = None
        if prompt_cache_path:
            self.prompt_cache_path = prompt_cache_path

            rkllm_load_prompt_cache = rkllm_lib.rkllm_load_prompt_cache
            rkllm_load_prompt_cache.argtypes = [RKLLM_Handle_t, ctypes.c_char_p]
            rkllm_load_prompt_cache.restype = ctypes.c_int
            rkllm_load_prompt_cache(self.handle, ctypes.c_char_p((prompt_cache_path).encode('utf-8')))
        
        self.tools = None
            
    def set_function_tools(self, system_prompt, tools, tool_response_str):
        if self.tools is None or not self.tools == tools:
            self.tools = tools
            self.set_function_tools_(self.handle, ctypes.c_char_p(system_prompt.encode('utf-8')), ctypes.c_char_p(tools.encode('utf-8')),  ctypes.c_char_p(tool_response_str.encode('utf-8')))

    def run(self, *param):
        role, enable_thinking, prompt = param
        rkllm_input = RKLLMInput()
        rkllm_input.role = role.encode('utf-8') if role is not None else "user".encode('utf-8')
        rkllm_input.enable_thinking = ctypes.c_bool(enable_thinking if enable_thinking is not None else False)
        rkllm_input.input_type = RKLLMInputType.RKLLM_INPUT_PROMPT
        rkllm_input.input_data.prompt_input = ctypes.c_char_p(prompt.encode('utf-8'))
        self.rkllm_run(self.handle, ctypes.byref(rkllm_input), ctypes.byref(self.rkllm_infer_params), None)
        return
    
    def abort(self):
        return self.rkllm_abort(self.handle)
    
    def release(self):
        self.rkllm_destroy(self.handle)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--rkllm_model_path', type=str, required=True, help='Absolute path of the converted RKLLM model on the Linux board;')
    parser.add_argument('--target_platform', type=str, required=True, help='Target platform: e.g., rk3588/rk3576;')
    parser.add_argument('--lora_model_path', type=str, help='Absolute path of the lora_model on the Linux board;')
    parser.add_argument('--prompt_cache_path', type=str, help='Absolute path of the prompt_cache file on the Linux board;')
    args = parser.parse_args()

    if not os.path.exists(args.rkllm_model_path):
        print("Error: Please provide the correct rkllm model path, and ensure it is the absolute path on the board.")
        sys.stdout.flush()
        exit()

    if not (args.target_platform in ["rk3588", "rk3576", "rv1126b", "rk3562"]):
        print("Error: Please specify the correct target platform: rk3588/rk3576/rv1126b/rk3562.")
        sys.stdout.flush()
        exit()

    if args.lora_model_path:
        if not os.path.exists(args.lora_model_path):
            print("Error: Please provide the correct lora_model path, and advise it is the absolute path on the board.")
            sys.stdout.flush()
            exit()

    if args.prompt_cache_path:
        if not os.path.exists(args.prompt_cache_path):
            print("Error: Please provide the correct prompt_cache_file path, and advise it is the absolute path on the board.")
            sys.stdout.flush()
            exit()

    # Fix frequency (optional on minimal images without sudo/scripts)
    fix_script = os.path.join(_SCRIPT_DIR, "fix_freq_{}.sh".format(args.target_platform))
    if os.path.exists(fix_script):
        subprocess.run(["bash", fix_script], check=False)
    else:
        print("skip fix_freq: {} not found".format(fix_script))
        sys.stdout.flush()

    # Set resource limit (best-effort)
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (102400, 102400))
    except Exception as e:
        print("skip setrlimit:", e)
        sys.stdout.flush()

    # Initialize RKLLM model
    print("=========init....===========")
    sys.stdout.flush()
    model_path = args.rkllm_model_path
    rkllm_model = RKLLM(model_path, args.lora_model_path, args.prompt_cache_path, args.target_platform)
    print("==============================")
    sys.stdout.flush()

    @app.route('/v1/models', methods=['GET'])
    def list_models():
        return jsonify({
            "object": "list",
            "data": [{
                "id": "Qwen2.5-Coder-3B",
                "object": "model",
                "owned_by": "rkllm"
            }]
        })

    @app.route('/v1/abort', methods=['POST', 'GET'])
    @app.route('/abort', methods=['POST', 'GET'])
    def abort_infer():
        """Stop in-flight RKLLM generation (client Ctrl+C / disconnect)."""
        global global_state
        try:
            print("abort requested", flush=True)
            rkllm_model.abort()
            global_state = -1
            return jsonify({"ok": True, "aborted": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    def _maybe_parse_tool_calls(text):
        """Convert model tool-call text into OpenAI tool_calls.

        Supports:
          - Qwen/RKLLM: <tool_call>{...}</tool_call>
          - Qwen2.5-Coder style: ```json\\n{\"name\":...,\"arguments\":...}\\n```
          - bare JSON object with name + arguments
        """
        if not text or not isinstance(text, str):
            return None, text

        calls = []
        cleaned = text

        def _obj_to_call(i, obj):
            if not isinstance(obj, dict):
                return None
            name = obj.get('name') or (obj.get('function') or {}).get('name')
            args = obj.get('arguments', obj.get('parameters', {}))
            if not name:
                return None
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            return {
                "id": "call_{}".format(i),
                "type": "function",
                "function": {"name": name, "arguments": args},
            }

        # 1) XML <tool_call> blocks
        if '<tool_call>' in text:
            for i, m in enumerate(re.finditer(r'<tool_call>\s*(.*?)\s*</tool_call>', text, re.DOTALL)):
                raw = m.group(1).strip()
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                call = _obj_to_call(i, obj)
                if call:
                    calls.append(call)
            if calls:
                cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL).strip()

        # 2) Markdown fenced JSON / bare JSON (Qwen2.5-Coder often does this)
        if not calls:
            candidates = []
            for m in re.finditer(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text, re.IGNORECASE):
                candidates.append((m.start(), m.end(), m.group(1).strip()))
            if not candidates:
                stripped = text.strip()
                if stripped.startswith('{') and '"name"' in stripped and (
                    '"arguments"' in stripped or '"parameters"' in stripped
                ):
                    candidates.append((0, len(text), stripped))

            for i, (_a, _b, raw) in enumerate(candidates):
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                call = _obj_to_call(i, obj)
                if call:
                    calls.append(call)

            if calls:
                # Remove fenced blocks; if whole reply was one JSON tool call, clear content.
                cleaned = re.sub(r'```(?:json)?\s*\{[\s\S]*?\}\s*```', '', text, flags=re.IGNORECASE).strip()
                if not cleaned:
                    stripped = text.strip()
                    if stripped.startswith('{') and '"name"' in stripped:
                        cleaned = None

        if not calls:
            return None, text
        return calls, cleaned or None

    def _extract_chat_request(data):
        """Parse OpenAI-style messages into one RKLLM prompt run."""
        messages = data.get('messages') or []
        enable_thinking = data.get('enable_thinking', False)
        tools = data.get('tools')
        sys_prompt = ""
        role = "user"
        input_prompt = None

        # Prefer last user/tool turn; keep latest system prompt.
        for message in messages:
            r = message.get('role')
            content = message.get('content', '')
            if isinstance(content, list):
                # multimodal OpenAI content parts -> plain text
                parts = []
                for p in content:
                    if isinstance(p, dict) and p.get('type') == 'text':
                        parts.append(p.get('text', ''))
                    elif isinstance(p, str):
                        parts.append(p)
                content = ''.join(parts)

            if r == 'system':
                sys_prompt = content or sys_prompt
            elif r == 'user':
                role = 'user'
                input_prompt = content
            elif r in ('tool', 'function'):
                role = 'tool'
                # RKLLM expects tool responses as a JSON array string, e.g. '["result"]'
                try:
                    parsed = json.loads(content) if isinstance(content, str) else content
                    if not isinstance(parsed, list):
                        parsed = [parsed]
                    input_prompt = json.dumps(parsed, ensure_ascii=False)
                except Exception:
                    input_prompt = json.dumps([content], ensure_ascii=False)
            elif r == 'assistant':
                # history is handled by client / keep_history=0 single-turn server
                continue

        return sys_prompt, role, input_prompt, enable_thinking, tools

    def _prepare_rkllm_run(role, enable_thinking, input_prompt, tools, sys_prompt):
        """Reset buffers and start inference thread; caller drains global_text."""
        global global_text, global_state, system_prompt, global_last_perf
        global_text = []
        global_state = -1
        global_last_perf = None
        if tools is not None:
            system_prompt = sys_prompt or system_prompt or "You are a helpful assistant."
            rkllm_model.set_function_tools(
                system_prompt=system_prompt,
                tools=json.dumps(tools),
                tool_response_str="tool_response",
            )

        model_thread = threading.Thread(
            target=rkllm_model.run,
            args=(role, enable_thinking, input_prompt),
        )
        model_thread.start()
        return model_thread

    def _run_rkllm(role, enable_thinking, input_prompt, tools, sys_prompt):
        model_thread = _prepare_rkllm_run(role, enable_thinking, input_prompt, tools, sys_prompt)
        rkllm_output = ""
        while True:
            while len(global_text) > 0:
                rkllm_output += global_text.pop(0)
            if not model_thread.is_alive():
                while len(global_text) > 0:
                    rkllm_output += global_text.pop(0)
                break
            model_thread.join(timeout=0.005)
        return rkllm_output

    def _sse_chunk(model_name, created, delta, finish_reason=None, usage=None):
        payload = {
            "id": "rkllm_chat",
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }],
        }
        if usage is not None:
            payload["usage"] = usage
        return "data: {}\n\n".format(json.dumps(payload, ensure_ascii=False))

    # Create a function to receive data sent by the user using a request
    # /v1/chat/completions: OpenAI-compatible for Qwen-Agent / openai clients
    @app.route('/rkllm_chat', methods=['POST'])
    @app.route('/v1/chat/completions', methods=['POST'])
    def receive_message():
        global is_blocking, global_state

        if is_blocking or global_state == 0:
            return jsonify({'status': 'error', 'message': 'RKLLM_Server is busy! Maybe you can try again later.'}), 503

        if not lock.acquire(blocking=False):
            return jsonify({'status': 'error', 'message': 'RKLLM_Server is busy! Maybe you can try again later.'}), 503

        is_blocking = True
        released = False

        def _release():
            nonlocal released
            global is_blocking
            if not released:
                released = True
                is_blocking = False
                lock.release()

        try:
            data = request.json
            if not data or 'messages' not in data:
                _release()
                return jsonify({'status': 'error', 'message': 'Invalid JSON data!'}), 400

            sys_prompt, role, input_prompt, enable_thinking, tools = _extract_chat_request(data)
            print("Received messages:", data.get('messages'))
            print("Parsed role/prompt:", role, (input_prompt[:120] + '...') if isinstance(input_prompt, str) and len(input_prompt) > 120 else input_prompt)

            if input_prompt is None or input_prompt == '':
                _release()
                return jsonify({'status': 'error', 'message': 'No user/tool message to run'}), 400

            use_stream = bool(data.get('stream'))
            model_name = data.get("model", "Qwen2.5-Coder-3B")
            created = int(time.time())

            # True token streaming: push SSE as RKLLM callback produces text.
            # When tools are enabled, buffer first: Qwen2.5-Coder often emits
            # tool JSON as plain text; streaming it confuses Qwen-Agent.
            if use_stream:
                model_thread = _prepare_rkllm_run(
                    role, enable_thinking, input_prompt, tools, sys_prompt
                )
                buffer_for_tools = tools is not None

                def generate():
                    full = ""
                    normal_done = False
                    try:
                        yield _sse_chunk(model_name, created, {"role": "assistant", "content": ""})
                        while True:
                            while len(global_text) > 0:
                                piece = global_text.pop(0)
                                full += piece
                                if not buffer_for_tools:
                                    yield _sse_chunk(model_name, created, {"content": piece})
                            if not model_thread.is_alive():
                                while len(global_text) > 0:
                                    piece = global_text.pop(0)
                                    full += piece
                                    if not buffer_for_tools:
                                        yield _sse_chunk(model_name, created, {"content": piece})
                                break
                            model_thread.join(timeout=0.01)

                        tool_calls, content = _maybe_parse_tool_calls(full)
                        finish = "tool_calls" if tool_calls else "stop"
                        if tool_calls:
                            yield _sse_chunk(
                                model_name,
                                created,
                                {
                                    "tool_calls": [{
                                        "index": i,
                                        "id": tc["id"],
                                        "type": "function",
                                        "function": tc["function"],
                                    } for i, tc in enumerate(tool_calls)],
                                },
                            )
                        elif buffer_for_tools and content:
                            # Flush buffered plain answer in one delta
                            yield _sse_chunk(model_name, created, {"content": content})
                        yield _sse_chunk(
                            model_name,
                            created,
                            {},
                            finish_reason=finish,
                            usage=_usage_from_perf(global_last_perf),
                        )
                        yield "data: [DONE]\n\n"
                        normal_done = True
                    except GeneratorExit:
                        # Client closed the SSE stream (e.g. Ctrl+C).
                        try:
                            rkllm_model.abort()
                        except Exception:
                            pass
                        raise
                    finally:
                        global global_state
                        if not normal_done:
                            try:
                                rkllm_model.abort()
                            except Exception:
                                pass
                            try:
                                model_thread.join(timeout=3)
                            except Exception:
                                pass
                            global_state = -1
                        _release()

                return Response(
                    generate(),
                    content_type="text/event-stream; charset=utf-8",
                )

            rkllm_output = _run_rkllm(role, enable_thinking, input_prompt, tools, sys_prompt)
            tool_calls, content = _maybe_parse_tool_calls(rkllm_output)

            message = {"role": "assistant", "content": content}
            finish = "stop"
            if tool_calls:
                message["tool_calls"] = tool_calls
                if content is None:
                    message["content"] = None
                finish = "tool_calls"
            resp = jsonify({
                "id": "rkllm_chat",
                "object": "chat.completion",
                "created": created,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "message": message,
                    "logprobs": None,
                    "finish_reason": finish,
                }],
                "usage": _usage_from_perf(global_last_perf),
            })
            _release()
            return resp, 200
        except Exception:
            _release()
            raise

    # Start the Flask application.
    # app.run(host='0.0.0.0', port=8080)
    app.run(host='0.0.0.0', port=8080, threaded=True, debug=False)

    print("====================")
    print("RKLLM model inference completed, releasing RKLLM model resources...")
    rkllm_model.release()
    print("====================")
