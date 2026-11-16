"""Read-oriented Linux diagnostics. Commands are fixed; user input is validated."""
import re
from .host_manager import connect_active_host

SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}$")

def _run(command: str, timeout=20) -> str:
    client = connect_active_host()
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return out if code == 0 else f"Command failed ({code}): {err or out}"
    finally:
        client.close()

def get_os_release() -> str:
    return _run("cat /etc/os-release 2>/dev/null || uname -a")

def get_cpu_load() -> str:
    return _run("cat /proc/loadavg; echo; head -n 5 /proc/stat")

def get_memory() -> str:
    return _run("cat /proc/meminfo | head -n 20")

def get_disk_usage() -> str:
    return _run("df -hT")

def get_process_list() -> str:
    return _run("ps -eo pid,ppid,user,%cpu,%mem,stat,comm --sort=-%cpu | head -n 31")

def get_java_processes() -> str:
    return _run("ps -eo pid,ppid,user,%cpu,%mem,args | grep '[j]ava' | head -n 40")

def get_listening_ports() -> str:
    return _run("ss -lntup 2>/dev/null || netstat -lntup 2>/dev/null || true")

def get_uptime() -> str:
    return _run("cat /proc/uptime; who -b 2>/dev/null || true")

def get_service_status(service_name: str) -> str:
    if not SERVICE_RE.fullmatch(service_name or ""):
        raise ValueError("Invalid service name.")
    return _run("systemctl status " + service_name + " --no-pager --full", timeout=25)

def get_network_interfaces() -> str:
    return _run("ip -brief address 2>/dev/null || ifconfig 2>/dev/null || true")

def get_top_processes_by_memory() -> str:
    return _run("ps -eo pid,user,%mem,%cpu,rss,comm --sort=-%mem | head -n 31")
