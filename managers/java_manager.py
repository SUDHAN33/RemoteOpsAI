"""Java process and log diagnostics. Configure allowed log roots per host."""
import re
from pathlib import PurePosixPath
from .host_manager import connect_active_host, get_active_profile

def _run(command: str, timeout=25) -> str:
    client = connect_active_host()
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return out if code == 0 else f"Command failed ({code}): {err or out}"
    finally:
        client.close()

def get_java_processes() -> str:
    return _run("ps -eo pid,ppid,user,%cpu,%mem,args | grep '[j]ava' | head -n 50")

def get_java_version() -> str:
    return _run("java -version 2>&1")

def get_jvm_memory(pid: int) -> str:
    if not isinstance(pid, int) or pid <= 1:
        raise ValueError("Invalid PID.")
    return _run(f"cat /proc/{pid}/status 2>/dev/null | grep -E '^(Name|VmPeak|VmSize|VmRSS|VmSwap|Threads):'")

def get_java_thread_count(pid: int) -> str:
    if not isinstance(pid, int) or pid <= 1:
        raise ValueError("Invalid PID.")
    return _run(f"ps -T -p {pid} -o pid,spid,stat,comm | head -n 100")

def _safe_log_path(relative_path: str) -> str:
    p = get_active_profile()
    allowed = p.get("log_dir", p.get("base_dir", "/home"))
    rel = PurePosixPath(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Use a relative path without '..'.")
    base = PurePosixPath(allowed)
    return str(base / rel)

def read_application_log(relative_path: str, max_lines: int = 200) -> str:
    if not isinstance(max_lines, int) or not 1 <= max_lines <= 1000:
        raise ValueError("max_lines must be between 1 and 1000.")
    path = _safe_log_path(relative_path)
    # Path has been restricted to a configured relative log root.
    return _run("tail -n " + str(max_lines) + " -- " + __import__("shlex").quote(path))

def search_application_log(relative_path: str, pattern: str, max_matches: int = 100) -> str:
    if not isinstance(max_matches, int) or not 1 <= max_matches <= 500:
        raise ValueError("max_matches must be between 1 and 500.")
    if not pattern or len(pattern) > 200:
        raise ValueError("Search pattern must be 1-200 characters.")
    path = _safe_log_path(relative_path)
    return _run("grep -Ein -- " + __import__("shlex").quote(pattern) + " " +
                __import__("shlex").quote(path) + " | head -n " + str(max_matches))

def find_java_exceptions(relative_path: str) -> str:
    return search_application_log(
        relative_path,
        r"Exception|Error|OutOfMemoryError|StackOverflowError|Caused by:"
    )

def get_application_health(url: str) -> str:
    # Only allow explicitly supplied HTTPS/HTTP URLs; curl does not follow redirects.
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValueError("Provide a valid http:// or https:// health URL.")
    # URL is quoted; command runs on remote host.
    return _run("curl --max-time 10 -sS -o /dev/null -w 'HTTP %{http_code}\\n' " +
                __import__("shlex").quote(url))
