
from mcp.server import MCPServer

from managers.ssh_manager import execute_command, create_ssh_client

from config import (
    REMOTE_HOST,
    REMOTE_PORT,
    REMOTE_USERNAME
)

from managers.sftp_manager import (
    list_remote_files,
    read_remote_file,
    upload_local_file,
    download_remote_file,
    create_remote_directory
)

from managers.ftp_manager import (
    connect as ftp_connect, status as ftp_status,
    list_directory as ftp_list_directory,
    change_directory as ftp_change_directory,
    upload_file as ftp_upload_file, download_file as ftp_download_file,
    create_directory as ftp_create_directory, delete_file as ftp_delete_file,
    rename_file as ftp_rename_file, disconnect as ftp_disconnect,
)

from managers.linux_system_manager import (
    get_cpu_usage,
    get_process_list,
    get_java_processes,
    get_listening_ports
)

from managers import host_manager as hosts
from managers import linux_manager as linux
from managers import java_manager as java
from managers import database_manager as db
from managers import certificate_manager as cert
from managers import docker_manager as docker

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

@mcp.tool()
def connect_ftp_server(profile_name: str, hostname: str, username: str, password: str,
                       port: int = 21, protocol: str = "FTP", timeout: int = 20,
                       passive: bool = True) -> str:
    """Connect using FTP or explicit FTPS. FTPS verifies server certificates."""
    return ftp_connect(profile_name, hostname, username, password, port, protocol, timeout, passive)

@mcp.tool()
def get_ftp_connection_status(profile_name: str) -> str:
    """Check an FTP profile and show its remote working directory."""
    return ftp_status(profile_name)

@mcp.tool()
def list_ftp_directory(profile_name: str, remote_path: str = ".") -> str:
    """List files and directories on an FTP server."""
    return ftp_list_directory(profile_name, remote_path)

@mcp.tool()
def change_ftp_directory(profile_name: str, remote_path: str) -> str:
    """Change the FTP session working directory."""
    return ftp_change_directory(profile_name, remote_path)

@mcp.tool()
def upload_ftp_file(profile_name: str, local_path: str, remote_path: str) -> str:
    """Upload a local file to an FTP server."""
    return ftp_upload_file(profile_name, local_path, remote_path)

@mcp.tool()
def download_ftp_file(profile_name: str, remote_path: str, local_path: str) -> str:
    """Download an FTP file to the local machine."""
    return ftp_download_file(profile_name, remote_path, local_path)

@mcp.tool()
def create_ftp_directory(profile_name: str, remote_path: str) -> str:
    """Create a directory on an FTP server."""
    return ftp_create_directory(profile_name, remote_path)

@mcp.tool()
def delete_ftp_file(profile_name: str, remote_path: str) -> str:
    """Delete a remote FTP file. Confirm the target before calling."""
    return ftp_delete_file(profile_name, remote_path)

@mcp.tool()
def rename_ftp_file(profile_name: str, source_path: str, destination_path: str) -> str:
    """Rename or move a remote FTP file."""
    return ftp_rename_file(profile_name, source_path, destination_path)

@mcp.tool()
def disconnect_ftp_server(profile_name: str) -> str:
    """Disconnect an FTP profile and clear its in-memory session."""
    return ftp_disconnect(profile_name)


# ==========================
# DOCKER TOOLS
# target="remote" (default): Docker on the active SSH host.
# target="local": Docker on the machine running this MCP server.
# ==========================

@mcp.tool()
def list_docker_containers(all_containers: bool = True, name_filter: str = "",
                           target: str = "remote") -> str:
    """List running and stopped Docker containers. target: 'remote' (active SSH host) or 'local'."""
    return docker.list_containers(all_containers, name_filter, target)


@mcp.tool()
def inspect_docker_container(container: str, target: str = "remote") -> str:
    """Summarize a container's configuration (state, ports, mounts, networks, env with secrets masked)."""
    return docker.inspect_container(container, target)


@mcp.tool()
def start_docker_container(container: str, target: str = "remote") -> str:
    """Start a stopped Docker container."""
    return docker.start_container(container, target)


@mcp.tool()
def stop_docker_container(container: str, timeout_seconds: int = 10, target: str = "remote") -> str:
    """Stop a running Docker container."""
    return docker.stop_container(container, timeout_seconds, target)


@mcp.tool()
def restart_docker_container(container: str, timeout_seconds: int = 10, target: str = "remote") -> str:
    """Restart a Docker container."""
    return docker.restart_container(container, timeout_seconds, target)


@mcp.tool()
def remove_docker_container(container: str, force: bool = False, remove_volumes: bool = False,
                            confirm: bool = False, target: str = "remote") -> str:
    """Remove a container. Destructive: does nothing unless confirm=True."""
    return docker.remove_container(container, force, remove_volumes, confirm, target)


@mcp.tool()
def get_docker_container_stats(container: str = "", target: str = "remote") -> str:
    """Show a CPU, memory and network snapshot for one container, or all running containers."""
    return docker.get_container_stats(container, target)


@mcp.tool()
def list_docker_images(name_filter: str = "", target: str = "remote") -> str:
    """List Docker images, optionally filtered by repository[:tag]."""
    return docker.list_images(name_filter, target)


@mcp.tool()
def inspect_docker_image(image: str, target: str = "remote") -> str:
    """Show image metadata (layers, config, env, entrypoint)."""
    return docker.inspect_image(image, target)


@mcp.tool()
def pull_docker_image(image: str, target: str = "remote") -> str:
    """Pull an image from a registry."""
    return docker.pull_image(image, target)


@mcp.tool()
def remove_docker_image(image: str, force: bool = False, confirm: bool = False,
                        target: str = "remote") -> str:
    """Remove an image. Destructive: does nothing unless confirm=True."""
    return docker.remove_image(image, force, confirm, target)


@mcp.tool()
def build_docker_image(context_path: str, tag: str, dockerfile: str = "", no_cache: bool = False,
                       target: str = "remote") -> str:
    """Build an image from a Dockerfile. context_path is an absolute path on the chosen target
    (e.g. C:\\src\\app locally, /srv/app remotely); dockerfile defaults to <context>/Dockerfile."""
    return docker.build_image(context_path, tag, dockerfile, no_cache, target)


@mcp.tool()
def tag_docker_image(source_image: str, target_tag: str, target: str = "remote") -> str:
    """Add a new tag to an existing image."""
    return docker.tag_image(source_image, target_tag, target)


@mcp.tool()
def get_docker_logs(container: str, tail: int = 100, since: str = "", timestamps: bool = False,
                    target: str = "remote") -> str:
    """Get container logs. since accepts durations like 30m or a timestamp."""
    return docker.get_logs(container, tail, since, timestamps, target)


@mcp.tool()
def execute_docker_command(container: str, command: str, user: str = "", workdir: str = "",
                           timeout_seconds: int = 60, target: str = "remote") -> str:
    """Run a shell command inside a running container (sh -c). workdir is a path inside the container."""
    return docker.execute_command(container, command, user, workdir, timeout_seconds, target)


@mcp.tool()
def get_docker_processes(container: str, ps_options: str = "", target: str = "remote") -> str:
    """List processes running inside a container (docker top)."""
    return docker.get_processes(container, ps_options, target)


@mcp.tool()
def get_docker_inspect(container: str, target: str = "remote") -> str:
    """Get the full raw `docker inspect` JSON for a container (env secrets masked)."""
    return docker.get_inspect(container, target)


@mcp.tool()
def get_docker_networks(name: str = "", target: str = "remote") -> str:
    """List Docker networks, or inspect one network when name is given."""
    return docker.get_networks(name, target)


@mcp.tool()
def get_docker_volumes(name: str = "", target: str = "remote") -> str:
    """List Docker volumes, or inspect one volume when name is given."""
    return docker.get_volumes(name, target)


@mcp.tool()
def list_docker_compose_projects(target: str = "remote") -> str:
    """List Docker Compose projects (running and stopped)."""
    return docker.list_compose_projects(target)


@mcp.tool()
def get_docker_compose_status(project_dir: str = "", project_name: str = "", service: str = "",
                              target: str = "remote") -> str:
    """Show service status for a Compose project. Give project_dir (absolute path on the target) and/or project_name."""
    return docker.get_compose_status(project_dir, project_name, service, target)


@mcp.tool()
def start_docker_compose_services(project_dir: str = "", project_name: str = "", services: str = "",
                                  target: str = "remote") -> str:
    """Start (docker compose up -d) all or the listed services (space/comma separated)."""
    return docker.start_compose_services(project_dir, project_name, services, target)


@mcp.tool()
def stop_docker_compose_services(project_dir: str = "", project_name: str = "", services: str = "",
                                 target: str = "remote") -> str:
    """Stop all or the listed Compose services without removing them."""
    return docker.stop_compose_services(project_dir, project_name, services, target)


@mcp.tool()
def restart_docker_compose_service(service: str, project_dir: str = "", project_name: str = "",
                                   target: str = "remote") -> str:
    """Restart a single Compose service."""
    return docker.restart_compose_service(service, project_dir, project_name, target)


@mcp.tool()
def get_docker_compose_logs(project_dir: str = "", project_name: str = "", service: str = "",
                            tail: int = 100, since: str = "", target: str = "remote") -> str:
    """Get logs for a Compose project or specific service(s)."""
    return docker.get_compose_logs(project_dir, project_name, service, tail, since, target)


@mcp.tool()
def deploy_docker_compose(project_dir: str, compose_content: str = "", compose_file: str = "",
                          pull: bool = True, target: str = "remote") -> str:
    """Deploy a Compose project. If compose_content is given it replaces the project's compose file
    after validation (old file kept as .bak.<timestamp>); then pulls images and runs up -d --remove-orphans.
    Invalid configurations are never deployed."""
    return docker.deploy_compose(project_dir, compose_content, compose_file, pull, target)


if __name__ == "__main__":
    mcp.run()
