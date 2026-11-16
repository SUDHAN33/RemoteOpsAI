
from ssh_manager import execute_command


def get_cpu_usage():
    result = execute_command(
        "cat /proc/loadavg"
    )

    return result["output"] or result["error"]


def get_process_list():
    result = execute_command(
        "ps -eo pid,ppid,user,%cpu,%mem,comm --sort=-%cpu | head -20"
    )

    return result["output"] or result["error"]


def get_java_processes():
    result = execute_command(
        "pgrep -af java || true"
    )

    return result["output"] or "No Java processes found"


def get_listening_ports():
    result = execute_command(
        "ss -lntup"
    )

    return result["output"] or result["error"]
