
import paramiko
from config import (
    REMOTE_HOST,
    REMOTE_PORT,
    REMOTE_USERNAME
)

from remoteops.host_manager import connect_active_host

def create_ssh_client():
    return connect_active_host()


def execute_command(command):
    """
    Execute a command on the remote Linux machine.
    """

    client = create_ssh_client()

    try:
        stdin, stdout, stderr = client.exec_command(
            command,
            timeout=30
        )

        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()

        return {
            "exit_code": exit_code,
            "output": output,
            "error": error
        }

    finally:
        client.close()
