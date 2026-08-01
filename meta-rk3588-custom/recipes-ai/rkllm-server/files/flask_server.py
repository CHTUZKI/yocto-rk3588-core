import ctypes
import sys
import os
import subprocess
import resource
import threading
import time
import argparse
import json
from collections import deque
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
global_text = deque()
global_state = -1
split_byte_data = bytes(b"") # Used to store the segmented byte data
# Last RKLLM performance sample, exposed in OpenAI usage for the benchmark tool.
global_last_perf = None
# Track recent tool calls to detect loops (tool_name, args_hash) -> count
_recent_tool_calls = {}

recevied_messages = []


def _capture_perf(result):
    global global_last_perf
    try:
        p = result.contents.perf
        sample = {
            "prefill_time_ms": float(p.prefill_time_ms),
            "prefill_tokens": int(p.prefill_tokens),
            "generate_time_ms": float(p.generate_time_ms),
            "generate_tokens": int(p.generate_tokens),
            "memory_usage_mb": float(p.memory_usage_mb),
        }
    except Exception:
        return
    if any(sample.values()):
        global_last_perf = sample


def _usage_from_perf(perf):
    if not perf:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    prompt = int(perf["prefill_tokens"])
    completion = int(perf["generate_tokens"])
    prefill_ms = float(perf["prefill_time_ms"])
    generate_ms = float(perf["generate_time_ms"])
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "rkllm": {
            **perf,
            "prefill_tokens_per_sec": prompt / (prefill_ms / 1000) if prefill_ms > 0 else None,
            "generate_tokens_per_sec": completion / (generate_ms / 1000) if generate_ms > 0 else None,
        },
    }

# Define the callback function
def callback_impl(result, userdata, state):
    global global_text, global_state, split_byte_data
    if state == LLMCallState.RKLLM_RUN_FINISH:
        global_state = state
        _capture_perf(result)
        print("\n", flush=True)
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

        # Bound generation for interactive Qwen3 use. The RKLLM ABI fixes
        # max_new_tokens at init, so the service setting is the hard ceiling.
        rkllm_param.max_context_len = int(os.environ.get("RKLLM_MAX_CONTEXT", "4096"))
        rkllm_param.max_new_tokens = int(os.environ.get("RKLLM_MAX_NEW_TOKENS", "768"))
        rkllm_param.skip_special_token = True
        rkllm_param.n_keep = -1
        rkllm_param.top_k = 1
        rkllm_param.top_p = 0.8
        rkllm_param.temperature = 0.7
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
                "id": "Qwen3-4B",
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

    def _parse_one_tool_json(raw, idx):
        """Parse one JSON object into an OpenAI tool_call, or return None."""
        try:
            obj = json.loads(raw)
        except Exception:
            return None
        name = obj.get("name") or obj.get("function", {}).get("name")
        if not name:
            return None
        args = obj.get("arguments", obj.get("parameters", {}))
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False)
        return {
            "id": "call_{}".format(idx),
            "type": "function",
            "function": {"name": name, "arguments": args},
        }

    def _maybe_parse_tool_calls(text):
        """Convert tool calls (XML-wrapped or raw JSON) into OpenAI tool_calls.

        Qwen3-4B on RKLLM sometimes outputs XML-wrapped tool calls and
        sometimes outputs bare JSON like {"name":"...","arguments":{...}}.
        Both must be recognised so AgentScope receives a proper tool_calls
        chunk instead of showing raw JSON to the user.
        """
        if not text:
            return None, text

        calls = []
        cleaned = text

        # 1) Parse XML-wrapped tool calls
        if '<tool_call>' in text:
            pattern = '<tool_call>' + r"\s*(.*?)\s*" + '</tool_call>'
            for m in re.finditer(pattern, text, re.DOTALL):
                raw = m.group(1).strip()
                tc = _parse_one_tool_json(raw, len(calls))
                if tc:
                    calls.append(tc)
            strip_pat = '<tool_call>' + r".*?" + '</tool_call>'
            cleaned = re.sub(strip_pat, "", text, flags=re.DOTALL).strip()

        # 2) Detect bare JSON tool calls (no XML wrapper).
        #    The model may output just {"name":"...","arguments":{...}}
        #    as plain text, or wrapped in markdown code blocks.
        if not calls:
            # First, extract JSON from markdown code blocks (```json ... ```)
            md_stripped = re.sub(r"```(?:json)?\s*", "", text)
            md_stripped = md_stripped.replace("```", "")
            stripped = md_stripped.strip()
            # Try the entire output as a single tool-call JSON
            tc = _parse_one_tool_json(stripped, 0)
            if tc:
                calls.append(tc)
                cleaned = None
            else:
                # Try line by line on the markdown-stripped text
                for line in stripped.splitlines():
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    tc = _parse_one_tool_json(line, len(calls))
                    if tc:
                        calls.append(tc)
                if calls:
                    # Remove matched JSON lines and markdown from visible content
                    lines_kept = []
                    for line in cleaned.splitlines():
                        s = line.strip()
                        # Skip markdown code block markers
                        if s.startswith("```"):
                            continue
                        if s.startswith("{") and s.endswith("}"):
                            try:
                                obj = json.loads(s)
                                if obj.get("name") and obj.get("arguments"):
                                    continue
                            except Exception:
                                pass
                        lines_kept.append(line)
                    cleaned = "\n".join(lines_kept).strip() or None

        if not calls:
            return None, text
        return calls, cleaned

    def _extract_chat_request(data):
        """Parse OpenAI-style messages into one RKLLM prompt run."""
        messages = data.get('messages') or []
        enable_thinking = data.get('enable_thinking', False)
        tools = data.get('tools')
        sys_prompt = ""
        role = "user"
        input_prompt = None
        dialog = []
        global _recent_tool_calls

        # Build a compact dialog history from all messages.  Each entry is
        # (speaker, text).  Assistant tool-call messages (content=null) are
        # summarised so the model remembers what it did.
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
                dialog.append(("用户", content))
            elif r in ('tool', 'function'):
                role = 'tool'
                # RKLLM expects tool responses as a JSON array of objects,
                # e.g. [{"result": "some text"}].  Wrap plain strings.
                raw_content = content
                if isinstance(raw_content, list):
                    # AgentScope may send content as a list of blocks
                    raw_content = " ".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in raw_content
                    )
                if not isinstance(raw_content, str):
                    raw_content = str(raw_content)
                # AgentScope sometimes sends the Python repr of a ToolResult
                # object as the content string, e.g.:
                # "content=[TextBlock(type='text', text='actual result', ...)] ..."
                # Extract the actual text from TextBlock(text='...') patterns.
                if "TextBlock(" in raw_content:
                    texts = re.findall(r"text='((?:[^'\\]|\\.)*)'", raw_content)
                    if texts:
                        raw_content = " ".join(texts)
                    else:
                        texts = re.findall(r'text="((?:[^"\\]|\\.)*)"', raw_content)
                        if texts:
                            raw_content = " ".join(texts)
                if not isinstance(raw_content, str):
                    raw_content = str(raw_content)
                input_prompt = json.dumps(
                    [{"result": raw_content}], ensure_ascii=False
                )
                # Record a short summary in the dialog so the model knows
                # the tool returned a result. Use cleaned raw_content.
                summary = (raw_content or "")[:200]
                dialog.append(("工具结果", summary))
            elif r == 'assistant':
                if isinstance(content, str) and content.strip():
                    # Truncate long assistant replies in the dialog history
                    # to avoid exceeding the 4096 token context window.
                    dialog.append(("助手", content[:300]))
                # If the assistant message has tool_calls (content=null),
                # record a summary so the model remembers what tool it called.
                tool_calls = message.get('tool_calls')
                if tool_calls:
                    names = []
                    for tc in tool_calls:
                        fn = tc.get('function', {}) if isinstance(tc, dict) else {}
                        names.append(fn.get('name', '?'))
                    dialog.append(("助手", f"[调用了工具: {', '.join(names)}]"))

        # --- Decide how to feed the prompt to RKLLM ---
        # RKLLM has no memory between HTTP requests (keep_history=0), so we
        # must embed conversation history into input_prompt every time.
        if role == 'user':
            # New user message: reset anti-loop tracking
            _recent_tool_calls = {}
        if role == 'user' and len(dialog) > 1 and input_prompt:
            # Last message is from the user: wrap full history.
            # Keep up to 20 recent dialog entries (covers ~5 turns with
            # tool calls) so early context like user's name is retained.
            recent = dialog[-20:]
            transcript = "\n".join(f"{speaker}：{text}" for speaker, text in recent[:-1])
            if tools:
                input_prompt = (
                    "以下是最近的对话历史，请保持上下文连续。\n"
                    f"{transcript}\n\n"
                    f"用户：{recent[-1][1]}"
                )
            else:
                input_prompt = (
                    "以下是最近的对话历史，请保持上下文连续。\n"
                    f"{transcript}\n\n"
                    f"用户：{recent[-1][1]}\n"
                    "请直接回答最后一个用户问题。"
                )
        elif role == 'tool' and len(dialog) > 1:
            # Last message is a tool result. RKLLM requires input_prompt to
            # be a pure JSON array like [{"result":"..."}].  But RKLLM has no
            # cross-request memory, so we must put the conversation context
            # into the system prompt instead.
            recent = dialog[-20:-1]  # everything except the final tool result
            transcript = "\n".join(f"{speaker}：{text}" for speaker, text in recent)

            # Global anti-loop detection: track tool calls across requests.
            # If the same tool+args has been called 2+ times already, force
            # the model to produce text by removing tools.
            # Build a key from the last assistant tool call in the dialog
            last_tc_key = None
            for speaker, text in reversed(recent):
                if speaker == "助手" and "[调用了工具:" in text:
                    last_tc_key = text
                    break
            if last_tc_key:
                _recent_tool_calls[last_tc_key] = _recent_tool_calls.get(last_tc_key, 0) + 1
                if _recent_tool_calls[last_tc_key] >= 2:
                    # Same tool called 2+ times — break the loop
                    tools = None
                    sys_prompt = (
                        f"{sys_prompt}\n\n"
                        "以下是最近的对话历史和工具执行结果。\n"
                        f"{transcript}\n\n"
                        "你已经成功执行了工具，现在请直接用文字总结结果并回答用户。"
                        "不要再调用任何工具，不要再输出 JSON，直接用中文回答。"
                    )
                    return sys_prompt, role, input_prompt, enable_thinking, tools

            sys_prompt = (
                f"{sys_prompt}\n\n"
                "以下是最近的对话历史，请根据上下文和工具执行结果回答用户。\n"
                f"{transcript}"
            )
            # input_prompt stays as the pure JSON tool result

        return sys_prompt, role, input_prompt, enable_thinking, tools

    def _prepare_rkllm_run(role, enable_thinking, input_prompt, tools, sys_prompt):
        """Reset buffers and start inference thread; caller drains global_text."""
        global global_text, global_state, system_prompt, global_last_perf
        global_text = deque()
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
                rkllm_output += global_text.popleft()
            if not model_thread.is_alive():
                while len(global_text) > 0:
                    rkllm_output += global_text.popleft()
                break
            model_thread.join(timeout=0.005)
        return rkllm_output

    _TOOL_OPEN = "<tool_call>"
    _TOOL_CLOSE = "</tool_call>"

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
            print(
                "Request: messages=%d prompt_chars=%d tools=%s thinking=%s stream=%s"
                % (
                    len(data.get("messages") or []),
                    len(input_prompt or ""),
                    bool(tools),
                    bool(enable_thinking),
                    bool(data.get("stream")),
                ),
                flush=True,
            )

            if input_prompt is None or input_prompt == '':
                _release()
                return jsonify({'status': 'error', 'message': 'No user/tool message to run'}), 400

            use_stream = bool(data.get('stream'))
            model_name = data.get("model", "Qwen3-4B")
            created = int(time.time())

            # True token streaming: push SSE as RKLLM callback produces text.
            if use_stream:
                model_thread = _prepare_rkllm_run(
                    role, enable_thinking, input_prompt, tools, sys_prompt
                )

                def generate():
                    full = ""
                    normal_done = False
                    in_tool_block = False
                    # When tools are enabled, buffer output until we can tell
                    # if it's a bare JSON tool call or normal text. This adds
                    # a small delay but prevents raw JSON from reaching the user.
                    pending = ""  # buffered text not yet streamed
                    try:
                        yield _sse_chunk(model_name, created, {"role": "assistant", "content": ""})
                        while True:
                            while len(global_text) > 0:
                                piece = global_text.popleft()
                                full += piece
                                if tools is not None:
                                    # XML tool call: suppress from content
                                    if _TOOL_OPEN in piece:
                                        in_tool_block = True
                                    if in_tool_block:
                                        if _TOOL_CLOSE in piece:
                                            in_tool_block = False
                                        continue
                                    # Bare JSON / markdown JSON tool call detection:
                                    # If full output so far looks like it's
                                    # starting a JSON object or a markdown
                                    # code block, buffer until we can determine
                                    # if it's a tool call.
                                    stripped_full = full.strip()
                                    if (stripped_full.startswith("{") and not stripped_full.startswith("{\n")) \
                                       or stripped_full.startswith("```"):
                                        pending += piece
                                        # Try to parse the accumulated buffer
                                        # Strip markdown code block markers
                                        parse_text = re.sub(r"```(?:json)?\s*", "", pending).replace("```", "").strip()
                                        try:
                                            obj = json.loads(parse_text)
                                            if obj.get("name") and obj.get("arguments"):
                                                # Confirmed tool call, discard pending
                                                pending = ""
                                                continue
                                            else:
                                                # Valid JSON but not a tool call, flush
                                                yield _sse_chunk(model_name, created, {"content": pending})
                                                pending = ""
                                        except Exception:
                                            # Incomplete JSON, keep buffering
                                            if len(pending) > 500:
                                                yield _sse_chunk(model_name, created, {"content": pending})
                                                pending = ""
                                            continue
                                    else:
                                        # Normal text - flush any pending first
                                        if pending:
                                            yield _sse_chunk(model_name, created, {"content": pending})
                                            pending = ""
                                yield _sse_chunk(model_name, created, {"content": piece})
                            if not model_thread.is_alive():
                                while len(global_text) > 0:
                                    piece = global_text.popleft()
                                    full += piece
                                    if tools is not None:
                                        if _TOOL_OPEN in piece:
                                            in_tool_block = True
                                        if in_tool_block:
                                            if _TOOL_CLOSE in piece:
                                                in_tool_block = False
                                            continue
                                        stripped_full = full.strip()
                                        if (stripped_full.startswith("{") and not stripped_full.startswith("{\n")) \
                                           or stripped_full.startswith("```"):
                                            pending += piece
                                            parse_text = re.sub(r"```(?:json)?\s*", "", pending).replace("```", "").strip()
                                            try:
                                                obj = json.loads(parse_text)
                                                if obj.get("name") and obj.get("arguments"):
                                                    pending = ""
                                                    continue
                                                else:
                                                    yield _sse_chunk(model_name, created, {"content": pending})
                                                    pending = ""
                                            except Exception:
                                                if len(pending) > 500:
                                                    yield _sse_chunk(model_name, created, {"content": pending})
                                                    pending = ""
                                                continue
                                        else:
                                            if pending:
                                                yield _sse_chunk(model_name, created, {"content": pending})
                                                pending = ""
                                    yield _sse_chunk(model_name, created, {"content": piece})
                                # Flush remaining pending buffer
                                if pending:
                                    try:
                                        obj = json.loads(pending)
                                        if obj.get("name") and obj.get("arguments"):
                                            pending = ""
                                        else:
                                            yield _sse_chunk(model_name, created, {"content": pending})
                                            pending = ""
                                    except Exception:
                                        yield _sse_chunk(model_name, created, {"content": pending})
                                        pending = ""
                                break
                            model_thread.join(timeout=0.01)

                        tool_calls, _content = _maybe_parse_tool_calls(full) if tools is not None else (None, full)
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
            tool_calls, content = _maybe_parse_tool_calls(rkllm_output) if tools is not None else (None, rkllm_output)

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
