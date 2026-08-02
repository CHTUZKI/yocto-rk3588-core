from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

import config

ROOT = Path(config.WORKSPACE).resolve()
# Only rm-family is denied. Everything else (dd, mkfs, fdisk, reboot, shutdown,
# systemctl, insmod, etc.) is allowed — the board is single-user root with
# debug-tweaks, and the agent needs real repair capability (restart services,
# sync time, fix network). rm is kept out because it's the one command that
# can brick the board with no undo and is almost never the right fix.
DENIED = {"rm", "rmdir", "unlink"}

# Sensitive files/dirs blocked from read_board_file / list_directory.
# Board is single-user root with debug-tweaks (no password), so this is a
# soft guard against the agent dumping secrets into chat history, not a
# hard security boundary.
READ_BLOCKED = {
    "/etc/shadow", "/etc/gshadow",
    "/root/.ssh", "/home/*/.ssh",
    "/etc/ssl/private",
}
READ_BLOCKED_NAMES = {".ssh", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}


def _response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _workspace_path(path: str) -> Path:
    """Resolve a path that MUST stay inside the Agent workspace (write/run)."""
    candidate = (ROOT / path).resolve() if not path.startswith("/") else Path(path).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError(f"path outside workspace: {path}")
    return candidate


def _board_path(path: str) -> Path:
    """Resolve an arbitrary board path for read-only tools, with a soft
    sensitive-file guard. Relative paths are still resolved under workspace
    so existing callers behave the same."""
    candidate = (ROOT / path).resolve() if not path.startswith("/") else Path(path).resolve()
    s = str(candidate)
    for blocked in READ_BLOCKED:
        if blocked.endswith("/*"):
            if s.startswith(blocked[:-1]) and any(p.name in READ_BLOCKED_NAMES
                                                  or p.name == ".ssh"
                                                  for p in (candidate, candidate.parent)):
                raise ValueError(f"path blocked by read policy: {path}")
        elif s == blocked or s.startswith(blocked + "/"):
            raise ValueError(f"path blocked by read policy: {path}")
    if candidate.name in READ_BLOCKED_NAMES:
        raise ValueError(f"path blocked by read policy: {path}")
    return candidate


def write_text_file(path: str, content: str) -> ToolResponse:
    """Write UTF-8 text to a file inside the Agent workspace.

    Args:
        path: Relative path under the Agent workspace.
        content: Complete UTF-8 file content.
    """
    try:
        target = _workspace_path(path)
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
        target = _workspace_path(path)
        content = target.read_text(encoding="utf-8")
        if len(content) > 8000:
            content = content[:8000] + "\n...[truncated]"
        return _response(content)
    except Exception as exc:
        return _response(f"error: read_file: {exc}")


def read_board_file(path: str) -> ToolResponse:
    """Read a UTF-8 text file anywhere on the board (read-only).

    Use this to inspect board files outside the Agent workspace, e.g.
    /etc/hostname, /proc/cpuinfo, /opt/models/, config files under /etc.
    Sensitive files (e.g. /etc/shadow, ~/.ssh/*) are blocked.

    Args:
        path: Absolute board path, e.g. /etc/hostname.
    """
    try:
        target = _board_path(path)
        if not target.is_file():
            return _response(f"error: not a regular file: {path}")
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > 8000:
            content = content[:8000] + "\n...[truncated]"
        return _response(content)
    except Exception as exc:
        return _response(f"error: read_board_file: {exc}")


def list_directory(path: str) -> ToolResponse:
    """List entries in a directory anywhere on the board (read-only).

    Use this when the user asks to "see files in a folder" or "what's in
    a directory". Returns one entry per line with a trailing / for dirs.
    Relative paths resolve under the Agent workspace; absolute paths are
    taken as-is (e.g. /home, /opt, /etc).

    Args:
        path: Directory path to list.
    """
    try:
        target = _board_path(path)
        if not target.is_dir():
            return _response(f"error: not a directory: {path}")
        entries = []
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            name = child.name + ("/" if child.is_dir() else "")
            entries.append(name)
        if not entries:
            return _response(f"(empty directory: {target})")
        out = "\n".join(entries)
        if len(out) > 8000:
            out = out[:8000] + "\n...[truncated]"
        return _response(f"{target}:\n{out}")
    except Exception as exc:
        return _response(f"error: list_directory: {exc}")


def run_python_file(path: str) -> ToolResponse:
    """Run a Python file inside the Agent workspace and return its output.

    Args:
        path: Relative path under the Agent workspace.
    """
    try:
        target = _workspace_path(path)
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
    """Run a board command with full shell support (pipes, redirects, chaining).

    Can run any shell command including pipes (|), redirects (> <), chaining
    (&& || ;), command substitution ($()), and backticks. This lets the agent
    do real diagnostics and repairs: chain ip/ping/curl, restart services via
    systemctl, sync time, edit config files, etc.

    The only restriction: rm/rmdir/unlink are blocked (no undo on eMMC).

    Args:
        command: Shell command, may include pipes, redirects, && / || / ; etc.
    """
    try:
        if not command.strip():
            return _response("error: empty command")
        # Block rm-family anywhere in the command (catches "rm", "/bin/rm",
        # "xargs rm", "find ... -delete" is allowed since -delete is not rm).
        # Use word-boundary regex to avoid false positives like "rmdir" caught
        # by "rm" — we list them explicitly instead.
        tokens = shlex.split(command)
        for token in tokens:
            base = token.rsplit("/", 1)[-1]
            if base in DENIED:
                return _response(
                    f"error: command blocked by safety policy: '{base}' is denied (no undo on eMMC)"
                )
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        output = output.strip()
        if len(output) > 8000:
            output = output[:8000] + "\n...[truncated]"
        return _response(f"exit={result.returncode}\n{output}")
    except Exception as exc:
        return _response(f"error: run_board_command: {exc}")


def set_system_time(time_str: str) -> ToolResponse:
    """Set the board system clock.

    The board has no RTC battery, so time resets on every power cycle. Use
    this to fix wrong time (which breaks SSL certificates and HTTPS).

    Args:
        time_str: Time in format "YYYY-MM-DD HH:MM:SS" (e.g. "2026-08-02 15:30:00").
    """
    try:
        result = subprocess.run(
            ["date", "-s", time_str],
            capture_output=True, text=True, timeout=5, check=False,
        )
        output = (result.stdout or "").strip()
        if result.returncode == 0:
            # Try to write to hardware clock if available
            subprocess.run(["hwclock", "-w"], capture_output=True, timeout=5)
            return _response(f"OK: system time set to {time_str}\n{output}")
        return _response(f"error: date -s failed (exit={result.returncode}): {result.stderr}")
    except Exception as exc:
        return _response(f"error: set_system_time: {exc}")


def sync_ntp(server: str = "pool.ntp.org") -> ToolResponse:
    """Sync system time from an NTP server or HTTP time API.

    Tries in order: ntpdate, chronyd, systemd-timesyncd restart, HTTP time API.
    The HTTP fallback (http://worldtimeapi.org/api/timezone/Etc/UTC) is used
    when NTP UDP port 123 is blocked but HTTPS works.

    Args:
        server: NTP server hostname, default pool.ntp.org.
    """
    import time as _time
    errors = []
    # Try ntpdate first
    try:
        r = subprocess.run(["ntpdate", server],
                           capture_output=True, text=True, timeout=15, check=False)
        if r.returncode == 0:
            return _response(f"OK: time synced via ntpdate {server}\n{r.stdout.strip()}")
        errors.append(f"ntpdate: {r.stderr.strip()}")
    except FileNotFoundError:
        errors.append("ntpdate: not installed")
    except Exception as e:
        errors.append(f"ntpdate: {e}")
    # Try chronyd
    try:
        r2 = subprocess.run(["chronyd", "-q", f"server {server} iburst"],
                            capture_output=True, text=True, timeout=30, check=False)
        if r2.returncode == 0:
            return _response(f"OK: time synced via chronyd {server}\n{r2.stdout.strip()}")
        errors.append(f"chronyd: {r2.stderr.strip()}")
    except FileNotFoundError:
        errors.append("chronyd: not installed")
    except Exception as e:
        errors.append(f"chronyd: {e}")
    # Try systemd-timesyncd (restart to pick up new config)
    try:
        subprocess.run(["timedatectl", "set-ntp", "true"],
                       capture_output=True, text=True, timeout=10, check=False)
        subprocess.run(["systemctl", "restart", "systemd-timesyncd"],
                       capture_output=True, text=True, timeout=10, check=False)
        _time.sleep(5)
        r3 = subprocess.run(["timedatectl", "status"],
                            capture_output=True, text=True, timeout=5, check=False)
        if "synchronized: yes" in (r3.stdout or "").lower():
            return _response(f"OK: time synced via systemd-timesyncd\n{r3.stdout.strip()}")
        errors.append(f"timesyncd: {r3.stdout.strip()}")
    except Exception as e:
        errors.append(f"timesyncd: {e}")
    # HTTP fallback: get time from worldtimeapi (works when NTP UDP is blocked)
    try:
        r4 = subprocess.run(
            ["bash", "-c", "curl -sS --max-time 10 http://worldtimeapi.org/api/timezone/Etc/UTC 2>/dev/null | grep -o '\"datetime\":\"[^\"]*\"' | cut -d'\"' -f4 | cut -d'.' -f1"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        http_time = (r4.stdout or "").strip()
        if http_time and "T" in http_time:
            date_part, time_part = http_time.split("T", 1)
            r5 = subprocess.run(["date", "-s", f"{date_part} {time_part}"],
                                capture_output=True, text=True, timeout=5, check=False)
            if r5.returncode == 0:
                subprocess.run(["hwclock", "-w"], capture_output=True, timeout=5)
                return _response(f"OK: time synced via HTTP API: {date_part} {time_part}")
        errors.append(f"http_api: got '{http_time}'")
    except Exception as e:
        errors.append(f"http_api: {e}")
    return _response("error: all sync methods failed\n" + "\n".join(errors))


def restart_service(name: str) -> ToolResponse:
    """Restart a systemd service on the board.

    Use this to apply config changes (e.g. after editing /etc/network/interfaces
    or fixing rkllm-server). Service name must be in the allowlist.

    Args:
        name: Service name, e.g. "rkllm-server", "networking", "systemd-timesyncd".
    """
    ALLOWED = {"rkllm-server", "networking", "systemd-timesyncd",
               "systemd-resolved", "sshd", "ssh"}
    try:
        if name not in ALLOWED:
            return _response(
                f"error: service '{name}' not in allowlist. "
                f"Allowed: {sorted(ALLOWED)}"
            )
        r = subprocess.run(["systemctl", "restart", name],
                           capture_output=True, text=True, timeout=30, check=False)
        if r.returncode == 0:
            # Check status
            s = subprocess.run(["systemctl", "is-active", name],
                               capture_output=True, text=True, timeout=5, check=False)
            status = s.stdout.strip() or "unknown"
            return _response(f"OK: {name} restarted, status={status}")
        return _response(f"error: systemctl restart {name} failed (exit={r.returncode}): {r.stderr.strip()}")
    except Exception as exc:
        return _response(f"error: restart_service: {exc}")


def diagnose_network() -> ToolResponse:
    """Run a full network diagnostic and return a report.

    Outputs: interfaces, routes, DNS, gateway ping, internet ping, DNS
    resolution, HTTPS test, current time (wrong time breaks SSL). Use this
    when the user reports network issues or HTTPS failures.
    """
    try:
        cmds = [
            ("interfaces", "ip -br addr show"),
            ("routes", "ip route show"),
            ("dns", "cat /etc/resolv.conf | grep nameserver"),
            ("gateway ping", "ping -c 2 -W 2 $(ip route | grep default | awk '{print $3}') 2>&1"),
            ("internet ping", "ping -c 2 -W 2 8.8.8.8 2>&1"),
            ("DNS resolve", "nslookup pool.ntp.org 2>&1 || getent hosts pool.ntp.org 2>&1"),
            ("HTTPS test", "curl -sS --max-time 5 -o /dev/null -w '%{http_code}' https://www.baidu.com 2>&1"),
            ("current time", "date"),
        ]
        out = []
        for label, cmd in cmds:
            r = subprocess.run(["bash", "-c", cmd],
                               capture_output=True, text=True, timeout=15, check=False)
            res = (r.stdout or r.stderr or "").strip()
            if len(res) > 1000:
                res = res[:1000] + "..."
            out.append(f"--- {label} ---\n{res}")
        report = "\n\n".join(out)
        if len(report) > 8000:
            report = report[:8000] + "\n...[truncated]"
        return _response(report)
    except Exception as exc:
        return _response(f"error: diagnose_network: {exc}")
