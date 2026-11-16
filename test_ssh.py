
from ssh_manager import execute_command

try:
    result = execute_command("hostname")

    print("Exit code:", result["exit_code"])
    print("Output:", result["output"])
    print("Error:", result["error"])

except Exception as e:
    print("SSH connection failed:", str(e))
