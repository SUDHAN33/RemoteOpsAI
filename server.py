
from mcp.server import MCPServer

from ssh_manager import execute_command, create_ssh_client

from config import (
    REMOTE_HOST,
    REMOTE_PORT,
    REMOTE_USERNAME
)

from sftp_manager import (
    list_remote_files,
    read_remote_file,
    upload_local_file,
    download_remote_file,
    create_remote_directory
)

from linux_system_manager import (
    get_cpu_usage,
    get_process_list,
    get_java_processes,
    get_listening_ports
)

from remoteops import host_manager as hosts
from remoteops import linux_manager as linux
from remoteops import java_manager as java
from remoteops import database_manager as db
from remoteops import certificate_manager as cert

# Initialize MCP server
mcp = MCPServer("RemoteOpsAI")


# TOOL 1: Check remote server connection

@mcp.tool()
def check_connection() -> str:
    """
    Check SSH connectivity to the configured remote Linux server.
    Does not depend on remote Linux shell commands.
    """

    client = None

    try:
        client = create_ssh_client()

        transport = client.get_transport()

        if transport and transport.is_active():
            return (
                "SSH connection successful!\n"
                f"Remote server: {REMOTE_HOST}\n"
                f"Port: {REMOTE_PORT}\n"
                f"Username: {REMOTE_USERNAME}\n"
                "SSH transport status: Active"
            )

        return "SSH connection established but transport is inactive."

    except Exception as e:
        return f"SSH connection failed: {str(e)}"

    finally:
        if client:
            client.close()



# TOOL 2: Get remote system information
@mcp.tool()
def get_system_information() -> str:
    """
    Get remote Linux system information.
    """

    command = (
        "cat /proc/sys/kernel/hostname 2>/dev/null; "
        "uname -a; "
        "uptime"
    )

    result = execute_command(command)

    if result["exit_code"] != 0:
        return (
            f"System information command failed:\n"
            f"{result['error']}"
        )

    return result["output"]


# TOOL 3: Check remote disk usage
@mcp.tool()
def get_disk_usage() -> str:
    """
    Get disk usage information from the remote Linux server.
    """

    result = execute_command("/usr/bin/df -h")

    return result["output"] or result["error"]


# TOOL 4: Check remote memory usage
@mcp.tool()
def get_memory_usage() -> str:
    """
    Get RAM and swap memory usage from the remote Linux server.
    """

    result = execute_command("free -h")

    return result["output"] or result["error"]


# TOOL 5: Check remote server uptime
@mcp.tool()
def get_server_uptime() -> str:
    """
    Get how long the remote Linux server has been running.
    """

    result = execute_command("uptime")

    return result["output"] or result["error"]


# TOOL 6: List remote directory
@mcp.tool()
def list_remote_directory(relative_path: str = ".") -> str:
    """
    List files and directories inside the configured remote directory.
    """

    try:
        files = list_remote_files(relative_path)

        if not files:
            return "Directory is empty"

        return "\n".join(
            f"{item['type']} | {item['name']} | {item['size']} bytes"
            for item in files
        )

    except Exception as e:
        return f"Directory listing failed: {e}"


# TOOL 7: Read remote file
@mcp.tool()
def read_remote_file_tool(relative_path: str) -> str:
    """
    Read a remote text file inside the configured base directory.
    """

    try:
        return read_remote_file(relative_path)

    except Exception as e:
        return f"File reading failed: {e}"


# TOOL 8: Upload local file
@mcp.tool()
def upload_local_file_tool(
    filename: str,
    remote_relative_path: str
) -> str:
    """
    Upload a file from the local uploads directory.
    Existing remote files are not overwritten.
    """

    try:
        return upload_local_file(filename, remote_relative_path)

    except Exception as e:
        return f"Upload failed: {e}"


# TOOL 9: Download remote file
@mcp.tool()
def download_remote_file_tool(relative_path: str) -> str:
    """
    Download a remote file into the local downloads directory.
    """

    try:
        return download_remote_file(relative_path)

    except Exception as e:
        return f"Download failed: {e}"


# TOOL 10: Create remote directory
@mcp.tool()
def create_remote_directory_tool(relative_path: str) -> str:
    """
    Create a directory inside the configured remote base directory.
    """

    try:
        return create_remote_directory(relative_path)

    except Exception as e:
        return f"Directory creation failed: {e}"


@mcp.tool()
def remote_cpu_usage() -> str:
    """Get remote server CPU load information."""
    return get_cpu_usage()


@mcp.tool()
def remote_process_list() -> str:
    """List the top remote server processes."""
    return get_process_list()


@mcp.tool()
def remote_java_processes() -> str:
    """Find running Java processes on the remote server."""
    return get_java_processes()


@mcp.tool()
def remote_listening_ports() -> str:
    """List listening network ports on the remote server."""
    return get_listening_ports()



from remoteops import host_manager as hosts


@mcp.tool()
def connect_remote_host(
    name: str,
    hostname: str,
    username: str,
    password: str,
    port: int = 22,
    base_dir: str = "/home"
) -> str:
    """
    Connect to a remote Linux server using SSH username and password.
    No SSH key path is required.
    """

    try:
        return hosts.connect_to_host(
            name=name,
            hostname=hostname,
            username=username,
            password=password,
            port=port,
            base_dir=base_dir
        )

    except Exception as e:
        return f"Remote connection failed: {e}"


@mcp.tool()
def list_remote_hosts() -> str:
    """List all registered remote host profiles."""

    return hosts.list_host_profiles()


@mcp.tool()
def switch_remote_host(name: str) -> str:
    """Switch to an existing remote host profile."""

    try:
        return hosts.set_active_host(name)

    except Exception as e:
        return f"Host switching failed: {e}"


@mcp.tool()
def get_active_remote_host() -> str:
    """Get details of the currently active remote host."""

    return hosts.get_active_host_summary()


@mcp.tool()
def verify_active_host_connection() -> str:
    """Verify the SSH connection to the active remote host."""

    client = None

    try:
        client = hosts.connect_active_host()

        profile = hosts.get_active_profile()

        return (
            "SSH connection successful!\n"
            f"Profile: {profile['profile_name']}\n"
            f"Host: {profile['hostname']}\n"
            f"Username: {profile['username']}\n"
            "Authentication: Password\n"
            "Status: Connected"
        )

    except Exception as e:
        return f"Connection verification failed: {e}"

    finally:
        if client:
            client.close()


@mcp.tool()
def disconnect_remote_host(name: str) -> str:
    """Clear the in-memory password for a host."""

    return hosts.disconnect_host(name)


@mcp.tool()
def list_remote_hosts() -> str:
    """List configured remote host profiles."""
    return hosts.list_host_profiles()


@mcp.tool()
def switch_remote_host(name: str) -> str:
    """Switch the active RemoteOps host."""
    return hosts.set_active_host(name)


@mcp.tool()
def get_active_remote_host() -> str:
    """Get the currently selected remote host."""
    return hosts.get_active_host_summary()


# ==========================
# LINUX ADMINISTRATION TOOLS
# ==========================

@mcp.tool()
def linux_os_information() -> str:
    """Get remote Linux distribution and OS information."""
    return linux.get_os_release()


@mcp.tool()
def linux_cpu_load() -> str:
    """Get remote CPU load averages and counters."""
    return linux.get_cpu_load()


@mcp.tool()
def linux_memory() -> str:
    """Get remote RAM and swap information."""
    return linux.get_memory()


@mcp.tool()
def linux_disk_usage() -> str:
    """Get remote filesystem usage."""
    return linux.get_disk_usage()


@mcp.tool()
def linux_processes() -> str:
    """List top remote processes by CPU."""
    return linux.get_process_list()


@mcp.tool()
def linux_java_processes() -> str:
    """List Java processes on the remote server."""
    return linux.get_java_processes()


@mcp.tool()
def linux_service_status(service_name: str) -> str:
    """Get the status of a systemd service."""
    return linux.get_service_status(service_name)


@mcp.tool()
def linux_listening_ports() -> str:
    """Get remote listening network ports."""
    return linux.get_listening_ports()


@mcp.tool()
def linux_network_interfaces() -> str:
    """Get network interface information."""
    return linux.get_network_interfaces()


@mcp.tool()
def linux_top_memory_processes() -> str:
    """List processes consuming the most memory."""
    return linux.get_top_processes_by_memory()


# ==========================
# JAVA DEBUGGING TOOLS
# ==========================

@mcp.tool()
def java_version() -> str:
    """Get remote Java runtime version."""
    return java.get_java_version()


@mcp.tool()
def java_processes() -> str:
    """List remote Java processes."""
    return java.get_java_processes()


@mcp.tool()
def java_memory(pid: int) -> str:
    """Get memory details for a Java process."""
    return java.get_jvm_memory(pid)


@mcp.tool()
def java_threads(pid: int) -> str:
    """Get thread information for a Java process."""
    return java.get_java_thread_count(pid)


@mcp.tool()
def java_read_log(
    relative_path: str,
    max_lines: int = 200
) -> str:
    """Read recent application log lines."""
    return java.read_application_log(relative_path, max_lines)


@mcp.tool()
def java_search_log(
    relative_path: str,
    pattern: str
) -> str:
    """Search application logs for a pattern."""
    return java.search_application_log(relative_path, pattern)


@mcp.tool()
def java_find_exceptions(relative_path: str) -> str:
    """Search application logs for Java exceptions."""
    return java.find_java_exceptions(relative_path)


@mcp.tool()
def java_application_health(url: str) -> str:
    """Check an application health endpoint from the remote server."""
    return java.get_application_health(url)


# ==========================
# DATABASE DIAGNOSTICS
# ==========================

@mcp.tool()
def postgres_version() -> str:
    """Get PostgreSQL version."""
    return db.postgres_version()


@mcp.tool()
def postgres_activity() -> str:
    """Inspect active PostgreSQL sessions."""
    return db.postgres_activity()


@mcp.tool()
def postgres_database_sizes() -> str:
    """Get PostgreSQL database sizes."""
    return db.postgres_database_sizes()


@mcp.tool()
def postgres_long_queries(min_seconds: int = 30) -> str:
    """Find long-running PostgreSQL queries."""
    return db.postgres_long_queries(min_seconds)


@mcp.tool()
def mysql_version() -> str:
    """Get MySQL version."""
    return db.mysql_version()


@mcp.tool()
def mysql_processlist() -> str:
    """Get MySQL process list."""
    return db.mysql_processlist()


@mcp.tool()
def mysql_database_sizes() -> str:
    """Get MySQL database sizes."""
    return db.mysql_database_sizes()


@mcp.tool()
def mysql_slow_query_settings() -> str:
    """Inspect MySQL slow query configuration."""
    return db.mysql_slow_query_settings()


# ==========================
# NETWORK CERTIFICATE TOOLS
# ==========================

@mcp.tool()
def inspect_tls_certificate(
    host: str,
    port: int = 443
) -> str:
    """Inspect the TLS certificate presented by a network endpoint."""
    return cert.inspect_tls_endpoint(host, port)


@mcp.tool()
def inspect_remote_certificate(relative_path: str) -> str:
    """Inspect a PEM or CRT certificate on the active remote server."""
    return cert.inspect_remote_pem_certificate(relative_path)


@mcp.tool()
def list_remote_certificate_files(
    relative_directory: str = "."
) -> str:
    """Find certificate files in the configured remote certificate directory."""
    return cert.list_remote_certificate_files(relative_directory)


@mcp.tool()
def verify_active_host_connection() -> str:
    """
    Verify SSH connectivity to the currently active host.
    Automatically discovers the SSH private key if needed.
    """

    client = None

    try:
        client = hosts.connect_active_host()

        profile = hosts.get_active_profile()

        return (
            "SSH connection successful!\n"
            f"Profile: {profile['profile_name']}\n"
            f"Host: {profile['hostname']}\n"
            f"Username: {profile['username']}\n"
            "Authentication: SSH key\n"
            "Connection status: Active"
        )

    except Exception as e:
        return f"Connection verification failed: {e}"

    finally:
        if client:
            client.close()


if __name__ == "__main__":
    mcp.run()
