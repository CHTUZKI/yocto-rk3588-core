from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

import config

ROOT = Path(config.WORKSPACE).resolve()
DENIED = {
    "rm", "rmdir", "unlink", "dd", "mkfs", "mkfs.ext4", "mkfs.vfat",
    "fdisk", "parted", "sfdisk", "wipefs", "sgdisk", "reboot", "shutdown",
    "poweroff", "halt", "init", "telinit", "passwd", "useradd", "userdel",
    "usermod", "groupadd", "groupdel", "systemctl", "insmod", "rmmod",
    "modprobe", "mkswap", "swapon", "swapoff", "chroot",
}


def _response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _safe_path(path: str) -> Path:
    candidate = (ROOT / path).resolve() if not path.startswith("/") else Path(path).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError(f"path outside workspace: {path}")
    return candidate


def write_text_file(path: str, content: str) -> ToolResponse:
    """Write UTF-8 text to a file inside the Agent workspace.

    Args:
        path: Relative path under the Agent workspace.
        content: Complete UTF-8 file content.
    """
    try:
        target = _safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return _response(f"wrote {target} ({len(content)} characters)")
    except Exception as exc:
        return _response(f"error: write_file: {exc}")


def read_text_file(path: str) -> ToolResponse:
    """Read a UTF-8 text file inside the Agent workspace.

    Args:
        path: Relative path under the Agent workspace.
    """
    try:
        target = _safe_path(path)
        content = target.read_text(encoding="utf-8")
        if len(content) > 8000:
            content = content[:8000] + "\n...[truncated]"
        return _response(content)
    except Exception as exc:
        return _response(f"error: read_file: {exc}")


def run_python_file(path: str) -> ToolResponse:
    """Run a Python file inside the Agent workspace and return its output.

    Args:
        path: Relative path under the Agent workspace.
    """
    try:
        target = _safe_path(path)
        result = subprocess.run(
            ["python3", str(target)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        output = output.strip()
        if len(output) > 8000:
            output = output[:8000] + "\n...[truncated]"
        return _response(f"exit={result.returncode}\n{output}")
    except Exception as exc:
        return _response(f"error: run_python_file: {exc}")


def run_board_command(command: str) -> ToolResponse:
    """Run one safe, non-interactive board command without shell operators.

    Args:
        command: A single command with arguments; pipes, redirects and shell chaining are not supported.
    """
    try:
        tokens = shlex.split(command)
        if not tokens:
            return _response("error: empty command")
        if any(token.rsplit("/", 1)[-1] in DENIED for token in tokens):
            return _response("error: command blocked by safety policy")
        if any(op in command for op in (";", "&&", "||", "|", ">", "<", "`", "$(")):
            return _response("error: shell operators are not supported")
        result = subprocess.run(
            tokens,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        output = output.strip()
        if len(output) > 8000:
            output = output[:8000] + "\n...[truncated]"
        return _response(f"exit={result.returncode}\n{output}")
    except Exception as exc:
        return _response(f"error: run_board_command: {exc}")
