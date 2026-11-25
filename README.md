# RemoteOpsAI

**Remote Linux Server Management through AI-powered MCP tools**

RemoteOpsAI is a Python-based Model Context Protocol (MCP) server that connects AI assistants such as GitHub Copilot Chat in Visual Studio Code to remote Linux servers over SSH.

It allows you to manage remote machines, inspect system resources, transfer files, execute Linux commands, and troubleshoot servers using natural-language instructions.

Instead of manually switching between SSH terminals, SFTP clients, and log files, you can interact with your remote infrastructure directly through GitHub Copilot Agent Mode.

---

## Features

### 1. Remote SSH Connection
- Connect to remote Linux servers using SSH.
- Authenticate using username and password.
- Maintain multiple remote host profiles.
- Switch between configured remote servers.
- Verify active SSH connections.
- Disconnect from remote hosts.
- Save newly encountered SSH host fingerprints to `known_hosts` using a Trust On First Use (TOFU) approach.

### 2. Linux Server Management
- Retrieve system information.
- Check disk availability and filesystem usage.
- Monitor memory usage.
- Retrieve server uptime.
- Execute remote Linux commands through the available command-execution tools.

`linux_run_command` runs through the SSH account's configured shell. It can source an explicit
project profile file from the remote user's home directory, then the applicable shell login
profile. If `bash` or `sh` is missing from PATH after profiles load, `/usr/bin:/bin` is
prepended for that command. It does not allocate a PTY or accept interactive input. See the
[project environment skill](.github/skills/project-environment/SKILL.md) for its workflow.
Restart the RemoteOpsAI MCP server and reconnect Copilot to load the updated command behavior
and skill.

### 3. Remote File Management (SFTP)
- List remote directories.
- Read remote files.
- Upload files from your local machine.
- Download files from remote servers.
- Create remote directories.

## RemoteOpsAI FTP / FTPS Add-on

**This add‑on introduces a dedicated FTP manager and a set of MCP tools for FTP/FTPS operations.** It works alongside the existing Paramiko‑based SSH/SFTP implementation without modifying it.

### Installation

1. Place `ftp_manager.py` in the `managers/` folder (it is already there in this repository).
2. Open `server_ftp_tools.py` and merge its import block and MCP tool definitions into your existing `server.py`. **Do not overwrite `server.py`.**
3. Python's `ftplib` is part of the standard library; no extra package is required.
4. Restart the MCP server / Copilot connection and verify the newly registered tools.

### Protocols

- **FTP** – plaintext, typically port 21. Credentials and file contents are not encrypted.
- **FTPS** – explicit FTP over TLS (also usually port 21). Certificate verification is enabled and the data channel is encrypted (`PROT P`).
- Implicit FTPS (often port 990) is **not** implemented in this add‑on.
- **SFTP** remains handled by the existing Paramiko SFTP manager.

### Tools

- `connect_ftp_server`
- `get_ftp_connection_status`
- `list_ftp_directory`
- `change_ftp_directory`
- `upload_ftp_file`
- `download_ftp_file`
- `create_ftp_directory`
- `delete_ftp_file`
- `rename_ftp_file`
- `disconnect_ftp_server`

### Example prompts

*Connect:* `Connect to ftp.example.com using profile vendor-ftp, username myuser, password I provide, port 21, protocol FTP.`

*FTPS:* `Connect to ftp.example.com using explicit FTPS, profile vendor‑ftps, port 21.`

*List:* `List /incoming using FTP profile vendor-ftp.`

*Upload:* `Upload C:\\Transfers\\report.csv to /incoming/report.csv using vendor-ftp.`

*Download:* `Download /outgoing/result.csv to C:\\Users\\me\\Downloads\\result.csv using vendor-ftp.`

*Disconnect:* `Disconnect FTP profile vendor-ftp.`

### Security and operational notes

- Prefer **FTPS** over plain FTP. Plain FTP sends credentials and data without encryption.
- FTPS validates the server certificate using the OS trust store. Do not disable validation; install the correct CA certificate instead.
- Passive mode is enabled by default. If listings or transfers hang, check the server's passive port range and firewall/NAT rules.
- Sessions and passwords are held in memory and disappear when the MCP process exits. Use unique profile names.
- The module uses process‑global session state and is intended for a single local MCP user, not a shared multi‑user HTTP deployment.
- `delete_ftp_file` is destructive; verify the target path before invoking it.

### 4. Docker and Docker Compose Management

Docker tools can manage Docker in two places, chosen per call with the optional `target` parameter:

- `target="remote"` (default): the Docker CLI over SSH on the **active remote host** (the same host used by the Linux tools).
- `target="local"`: the Docker CLI on the **machine running RemoteOpsAI** (e.g. Docker Desktop on Windows). No SSH connection or active host is needed. Commands run directly without a shell.

If you don't mention "local", Copilot uses the remote host. Ask for the local engine explicitly, e.g. *"List my **local** Docker containers"*.

**Requirements on the remote host:** Docker Engine installed and the SSH user able to run `docker` (member of the `docker` group). If `sudo` is required instead, add `"docker_command": "sudo -n docker"` to that host's entry in `data/hosts.json` (password-less sudo for docker is needed). Compose requires the Docker Compose v2 plugin (`docker compose`).

**Requirements for local Docker:** Docker Desktop (Windows/macOS) or Docker Engine (Linux) running, with `docker` on `PATH` for the process that starts the MCP server. For local tools, `context_path` and `project_dir` are local absolute paths (e.g. `C:\src\orders`); `workdir` is always a path inside the container (e.g. `/app`).

| Group | MCP tools |
|---|---|
| Container management | `list_docker_containers`, `inspect_docker_container`, `start_docker_container`, `stop_docker_container`, `restart_docker_container`, `remove_docker_container`, `get_docker_container_stats` |
| Image management | `list_docker_images`, `inspect_docker_image`, `pull_docker_image`, `remove_docker_image`, `build_docker_image`, `tag_docker_image` |
| Container debugging | `get_docker_logs`, `execute_docker_command`, `get_docker_processes`, `get_docker_inspect`, `get_docker_networks`, `get_docker_volumes` |
| Docker Compose | `list_docker_compose_projects`, `get_docker_compose_status`, `start_docker_compose_services`, `stop_docker_compose_services`, `restart_docker_compose_service`, `get_docker_compose_logs`, `deploy_docker_compose` |

Every tool accepts `target`. `inspect_docker_container` returns a readable summary, while `get_docker_inspect` returns the full raw JSON; both mask environment variables whose names look sensitive (password, secret, token, key). `get_docker_networks` and `get_docker_volumes` list everything, or inspect one item when `name` is given.

**Compose projects** are identified by an absolute `project_dir` on the chosen target and/or a `project_name` (as shown by `list_docker_compose_projects`). `deploy_docker_compose` can optionally write new `compose_content`. It replaces the file Compose would normally load (`compose.yaml`, `compose.yml`, `docker-compose.yaml` or `docker-compose.yml`, unless `compose_file` is given). The new content is staged next to the current file and validated with `docker compose config -q`, together with any override file that is present. Only then is it installed; the previous file is kept as `<file>.bak.<timestamp>`. The deploy then runs `pull` (unless `pull=False`) and `up -d --remove-orphans`. Invalid configurations are never deployed.

**Safety notes**
- Container/image names, service names, users and paths are validated and shell-quoted before use.
- `remove_docker_container` and `remove_docker_image` do nothing unless `confirm=True` is passed.
- `execute_docker_command` runs arbitrary commands inside the container with the privileges of the chosen container user; review commands before approving them.
- Output is truncated to 60,000 characters per call.

**Example prompts**
- `List all Docker containers on the active host and show stats for the running ones.`
- `Show the last 100 log lines of the orders-api container from the past 30 minutes.`
- `Run psql -U app -c "\dt" inside the postgres container.`
- `Build /srv/orders as orders-api:1.4, tag it as orders-api:latest, then restart the api service in /opt/orders.`
- `Deploy this updated docker-compose.yml to /opt/orders and show the service status.`
- `List my local Docker containers and show stats for the running ones.`
- `Build C:\src\orders locally as orders-api:dev and show the image details.`
- `Start the local compose project in C:\dev\shop and show the web service logs.`

### 5. Application and Infrastructure Troubleshooting

The project is designed to support additional diagnostic modules, including:

- Java application troubleshooting.
- Application log analysis.
- JVM and memory diagnostics.
- PostgreSQL and MySQL diagnostics.
- SSL/TLS certificate inspection.
- Java keystore inspection.
- JBoss EAP, WildFly, and Tomcat troubleshooting.
- Application deployment and verification.

**Note:** Availability of these capabilities depends on which modules and tools have been integrated into your current version of the repository. The planned modules are not necessarily exposed as MCP tools yet.

### 6. Java Keystore Certificate Inspection

`inspect_remote_keystore` uses the active SSH host's `keytool -list -v` to read
certificate subjects, issuers, chains, validity dates and fingerprints without
changing the keystore. Formats include JKS and PKCS12 when supported by the remote JDK.

- `relative_path`: path relative to the profile's `certificate_dir`, or `base_dir`
  if unset. Absolute paths and `..` components are rejected.
- `store_password` (optional): verifies integrity. It is sent through SSH standard
  input, not included in the remote command line or saved by this tool. Without it,
  integrity is **not verified** and some store types may hide entries.
- `alias` (optional): inspect one entry.
- `keytool_path` (default `keytool`): remote executable name or absolute JDK keytool path.

This inspects a supplied file, not the live TLS endpoint. It does not automatically
discover the application's keystore or verify endpoint hostname/trust.

### 7. Cross-host Java Trust and HTTP/HTTPS Diagnostics

These tools reuse named SSH profiles and cached credentials without switching the
active host:

| MCP tool | Purpose |
|---|---|
| `inspect_java_tls_configuration(profile_name, pid=None)` | Discover JVM executables, truststore paths and JBoss bind addresses without returning passwords. |
| `compare_java_truststores(first_profile, first_pid, second_profile, second_pid)` | Compare exact SHA256 file hashes and certificate fingerprint lists, including duplicates. |
| `probe_java_http_connection(profile_name, pid, url, address_override=None, timeout_seconds=6)` | Issue a direct HTTP/HTTPS GET from a selected host using the selected JVM's JDK and truststore settings. |

First connect both profiles using `connect_remote_host`. Discover the application
PIDs, compare their truststores, then probe each direction separately. HTTP responses
include their status code; DNS, connection and TLS failures are returned explicitly
as `result.status="error"` with exception details. A 4xx/5xx response establishes
connectivity, not application health.

For example, after discovering the appropriate PID:

```text
probe_java_http_connection(
    profile_name="source",
    pid=12345,
    url="https://target.example.net:8443/",
    address_override="192.0.2.20"
)
```

Omit `address_override` for the normal DNS test. An override preserves the URL's
hostname for TLS/SNI and changes resolution only for that probe. It does not repair
system DNS. HTTPS always validates certificate trust and hostname; plain HTTP
does not use a truststore.

**Requirements:** Linux SSH hosts, readable JVM process information/truststores,
the selected JDK's `keytool` for comparison, JDK 17+ for probes and JDK 18+ for DNS
overrides. Connect again if a profile's SSH password is no longer cached.

**Safety and scope:** Truststore passwords are read from JVM command-line properties
when present, sent through SSH standard input, and never returned, stored in temporary
files, or included in probe process arguments. Keytool integrity warnings are
preserved. The probe creates a private temporary directory and removes its source
and optional hosts file afterwards. It makes one direct GET, bypasses proxies,
does not follow redirects, sends no client certificate and reads no response body.
It runs a fresh JVM: application-defined SSL contexts, runtime property changes,
provider overrides, mutual TLS and application proxy settings are outside its scope.

See the [Java connectivity skill](.github/skills/java-connectivity/SKILL.md) for the
full diagnostic workflow. It uses Copilot's repository skill location. Restart the
MCP server / reconnect Copilot to load the tools.

### 8. Windows Remote Administration (PowerShell Remoting)

Windows servers are managed with the same workflow as Linux hosts, using a username and
password over **PowerShell Remoting (WinRM)**. No SSH server is needed on the Windows host.

| Area | MCP tools |
|---|---|
| Connection | `connect_windows_host`, `list_windows_hosts`, `switch_windows_host`, `verify_windows_connection`, `disconnect_windows_host` |
| Command execution | `windows_run_powershell`, `windows_run_command` |
| Files (confined to the profile's `base_dir`) | `windows_list_directory`, `windows_read_file`, `windows_upload_file`, `windows_download_file`, `windows_create_directory` |
| Diagnostics | `windows_system_information`, `windows_uptime`, `windows_cpu_usage`, `windows_memory`, `windows_disk_usage`, `windows_processes`, `windows_top_memory_processes`, `windows_java_processes`, `windows_listening_ports`, `windows_network_interfaces`, `windows_service_status` |

**Connecting.** Use `MACHINE\user` or `DOMAIN\user` as the username. Port 5985 (HTTP) uses
NTLM with mandatory message encryption; `use_https=true` uses port 5986 with full certificate
validation (`ca_bundle_path` accepts a private CA's PEM file). Certificate validation is
never disabled and Basic authentication is not supported. The password stays in process
memory only; profiles without passwords are saved in `data/windows_hosts.json`. Each tool
accepts an optional `profile_name` and otherwise uses the active Windows host.

**Preparing the Windows host** (as an Administrator, once):

```powershell
Enable-PSRemoting -Force
Add-LocalGroupMember -SID 'S-1-5-32-580' -Member 'MACHINE\user'   # Remote Management Users, if not an Administrator
```

Restrict the firewall rule to your management network. Remote Desktop (3389) is a separate
service and does not by itself enable WinRM.

**Files.** `base_dir` (default `C:\`) confines file tools: absolute paths, drive letters,
`..`, alternate data streams, reserved device names and directory junctions/symlinks are
rejected. Reads are limited to 1 MB; uploads and downloads to 100 MB, are verified with
SHA256, and never overwrite existing files. Uploads come from `uploads/` and downloads go to
`downloads/`.

**Commands.** `windows_run_powershell` and `windows_run_command` run arbitrary code with the
connected account's privileges and are not confined to `base_dir`; review commands before
approving them. Output is truncated at 60,000 characters and timeouts range from 1 to 600
seconds.

**Non-administrator accounts.** Accounts in Remote Management Users cannot use WMI/CIM.
Diagnostics then use registry, .NET and `netstat` data and say so; uptime becomes approximate
and Java command lines are unavailable. After a command timeout, child processes may survive
unless the account may use WMI.

**Requirement:** `pypsrp` (`pip install pypsrp`). It is imported only when a Windows tool is
used, so the server still starts without it.

See the [Windows remote administration skill](.github/skills/windows-remote-administration/SKILL.md)
for the full workflow and troubleshooting (HTTP 401, access denied, TLS errors).

---

## Architecture

```text
+--------------------------------------+
|       Visual Studio Code             |
|                                      |
|       GitHub Copilot Chat            |
|       Agent Mode                     |
+------------------+-------------------+
                   |
                   | MCP Protocol
                   | STDIO Transport
                   |
+------------------v-------------------+
|             RemoteOpsAI              |
|                                      |
|              server.py               |
|                                      |
|  +-------------+  +---------------+ |
|  | SSH Manager |  | SFTP Manager  | |
|  +-------------+  +---------------+ |
|                                      |
|  +-------------+  +---------------+ |
|  | Host Manager|  | System Tools  | |
|  +-------------+  +---------------+ |
|                                      |
|  +-------------+  +---------------+ |
|  | Java Tools  |  | Database Tools| |
|  +-------------+  +---------------+ |
+------------------+-------------------+
                   |
                   | SSH / SFTP
                   |
+------------------v-------------------+
|          Remote Linux Servers        |
|                                      |
|  Server 1       Server 2      Server 3|
|                                      |
|  Linux          Linux         Linux  |
|  Java           PostgreSQL    MySQL  |
|  JBoss          Applications  Logs   |
+--------------------------------------+
```

### How it works

1. GitHub Copilot receives your natural-language request.
2. Copilot selects the appropriate RemoteOpsAI MCP tool.
3. RemoteOpsAI establishes an SSH connection to the selected server.
4. The requested command or file operation is performed remotely.
5. The result is returned to Copilot for analysis and presentation.

---

## Prerequisites

Install the following on your Windows machine:

| Requirement | Purpose |
|---|---|
| Python 3.10+ | Run the MCP server |
| Git | Clone and update the repository |
| Visual Studio Code | Development environment |
| GitHub Copilot Chat | AI assistant |
| GitHub Copilot Agent Mode with MCP support | Execute MCP tools |
| SSH access | Connect to remote Linux servers |

The remote Linux machine must have SSH access enabled and the account must have the permissions required for the requested operations.

---

## Installation

### Step 1: Clone the repository

Open PowerShell:

```powershell
git clone https://github.com/YOUR_USERNAME/RemoteOpsAI.git

cd RemoteOpsAI
```

Replace `YOUR_USERNAME` with your GitHub username.

### Step 2: Create a Python virtual environment

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate the environment again.

### Step 3: Install dependencies

```powershell
python -m pip install --upgrade pip

pip install -r requirements.txt
```

If your repository does not yet contain `requirements.txt`, create it with the dependencies used by your implementation. For example:

```text
mcp
paramiko
pypsrp
python-dotenv
```

Keep this file aligned with the actual packages imported by your project.

### Step 4: Configure environment variables

If your implementation uses a `.env` file, create it in the repository root.

Example:

```env
# Default remote server configuration, if used by your implementation
REMOTE_HOST=your-server-hostname
REMOTE_PORT=22
REMOTE_USERNAME=your-username
REMOTE_BASE_DIR=/home
```

Use the variable names expected by your actual `config.py`.

**Important:** Do not put SSH passwords in `.env`, source code, or GitHub. RemoteOpsAI's password-based host manager keeps entered passwords in memory for the current MCP process.

### Step 5: Start the MCP server manually

Run:

```powershell
python server.py
```

The server should start using its configured MCP transport.

For a stdio-based MCP server, it is normal for the process to remain running without displaying a conventional web page. Copilot will launch and communicate with the server when needed.

Stop the manual process with `Ctrl + C` before testing through another MCP client.

---

## Configure RemoteOpsAI in Visual Studio Code

The following instructions configure RemoteOpsAI for personal use across your VS Code workspaces on the current computer.

### Step 1: Open Visual Studio Code

Open VS Code and sign in to GitHub Copilot.

Open Copilot Chat and select **Agent** mode.

### Step 2: Open MCP server configuration

Press:

```text
Ctrl + Shift + P
```

Search for:

```text
Chat: Open Customizations
```

Open the **MCP Servers** section.

Select **Add Server**.

Choose:

- Server type: `Command (stdio)`
- Server name: `remoteOpsAI`
- Configuration destination: `Global > Copilot Global`

### Step 3: Configure the launch command

Use the following values.

**Command:**

```text
C:\Users\YOUR_USERNAME\RemoteOpsAI\.venv\Scripts\python.exe
```

**Arguments:**

```text
C:\Users\YOUR_USERNAME\RemoteOpsAI\server.py
```

Replace `YOUR_USERNAME` with your Windows username and adjust the repository path if you cloned it somewhere else.

The equivalent native Copilot configuration is:

```json
{
  "mcpServers": {
    "remoteOpsAI": {
      "type": "stdio",
      "command": "C:\\Users\\YOUR_USERNAME\\RemoteOpsAI\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\YOUR_USERNAME\\RemoteOpsAI\\server.py"
      ]
    }
  }
}
```

For manual configuration, save this in:

```text
%USERPROFILE%\.copilot\mcp-config.json
```

If you use a custom `COPILOT_HOME`, use its `mcp-config.json` instead.

### Step 4: Restart and verify

Restart the Copilot MCP connection or open a new Copilot session.

In Copilot Chat, ask:

```text
List the available RemoteOpsAI tools.
```

You should see the tools exposed by your MCP server, such as:

- `check_connection`
- `get_system_information`
- `get_disk_usage`
- `get_memory_usage`
- `get_server_uptime`
- `list_remote_directory`
- `read_remote_file_tool`
- `upload_local_file_tool`
- `download_remote_file_tool`
- `create_remote_directory_tool`

The exact list depends on the tools registered in `server.py`.

---

## Connect to a Remote Linux Server

Once RemoteOpsAI is available in Copilot, use natural-language instructions.

### Example 1: Connect to a server

```text
Connect to the remote Linux server using these details:

Profile name: pgstorage1
Hostname: pgstorage1
Username: chp
Port: 22
Password: <enter password>
```

Use your actual hostname, username, and password.

The connection tool should verify the SSH connection and activate the selected host profile.

### Example 2: Check server connectivity

```text
Check the SSH connection to the active remote server.
```

### Example 3: Check disk usage

```text
Check disk availability on the active remote server.

Show:
- Filesystem
- Total size
- Used space
- Available space
- Usage percentage
```

### Example 4: Check memory

```text
Get the memory usage of the active Linux server.

Show total memory, used memory, free memory and available memory.
```

### Example 5: Inspect a remote directory

```text
List all files and directories under /home/chp.
```

### Example 6: Read an application log

```text
Read the last 200 lines from:

/opt/application/logs/server.log

Identify errors, exceptions and warnings.
```

### Example 7: Upload a file

```text
Upload this local file:

C:\Users\YOUR_USERNAME\Desktop\config.properties

To the remote server:

/home/chp/config.properties
```

### Example 8: Download a file

```text
Download the following remote file:

/home/chp/application.log

Save it to:

C:\Users\YOUR_USERNAME\Downloads
```

### Example 9: Switch remote servers

```text
Switch the active remote connection to pgstorage2.
```

These are example prompts. Actual functionality depends on the registered tools and their arguments.

---

## Use RemoteOpsAI on Multiple Computers

One of the main goals of this project is to use the same MCP server implementation from multiple machines.

You can achieve this by publishing the source code to a GitHub repository.

### On your first computer

Commit and push your project:

```powershell
cd C:\Users\YOUR_USERNAME\RemoteOpsAI

git init

git add .

git commit -m "Initial RemoteOpsAI MCP implementation"

git branch -M main

git remote add origin https://github.com/YOUR_USERNAME/RemoteOpsAI.git

git push -u origin main
```

### On your second computer

Clone the same repository:

```powershell
git clone https://github.com/YOUR_USERNAME/RemoteOpsAI.git

cd RemoteOpsAI

python -m venv .venv

.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Configure the MCP server in that computer's Copilot configuration using its own Python executable and local repository path.

Repeat the same steps for other computers.

### Updating the project

Whenever you publish changes from your development computer:

```powershell
git add .

git commit -m "Update RemoteOpsAI"

git push
```

On the other computers:

```powershell
git pull

pip install -r requirements.txt
```

Restart the MCP server or Copilot connection after updating.

**Important:** GitHub shares your source code, not your active SSH sessions or passwords. Each computer must establish its own remote connections and provide its own credentials.

---

## Security Considerations

RemoteOpsAI can execute commands and access files on remote servers. Use it carefully.

### SSH authentication

- Use dedicated Linux accounts where possible.
- Grant only the permissions required for the tasks.
- Avoid running routine operations as `root`.
- Never commit passwords or private keys to GitHub.
- Passwords held by the current host manager are stored in process memory and are lost when that process exits.

### SSH host key verification

RemoteOpsAI can save a previously unseen SSH host key to the local `known_hosts` file using its TOFU policy.

The usual location on Windows is:

```text
%USERPROFILE%\.ssh\known_hosts
```

This avoids repeatedly blocking connections to new servers.

However, automatically trusting a first-seen key does not independently prove the server's identity. For production environments, verify the server fingerprint through a trusted channel before accepting it.

If a previously trusted server presents a different host key, investigate the change. Do not automatically overwrite an existing fingerprint.

### GitHub repository

Do not commit:

```text
.env
.venv/
__pycache__/
*.pyc
known_hosts
passwords.txt
credentials.json
```

A suggested `.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
*.pyd
.Python

# Virtual environment
.venv/
venv/

# Environment and secrets
.env
.env.*
!.env.example
credentials.json
passwords.txt

# SSH files
known_hosts
*.pem
*.key

# Logs
*.log

# Local transfers
uploads/*
downloads/*

# IDE
.vscode/
.idea/
```

Review the ignore rules before committing. Do not ignore project configuration files that are required to run the server.

---

## Troubleshooting

### 1. MCP server is not appearing in Copilot

Check that:

- Python is installed.
- The virtual environment exists.
- All dependencies are installed.
- The configured Python executable path is correct.
- The `server.py` path is correct.
- Copilot is using the intended MCP configuration.

Try running the server manually:

```powershell
.\.venv\Scripts\python.exe server.py
```

### 2. SSH connection failed

Check:

- Hostname or IP address.
- SSH port, usually `22`.
- Username and password.
- Network connectivity.
- Remote SSH service status.
- Firewall rules.
- Whether password authentication is enabled on the remote server.

### 3. Host key verification failed

Inspect:

```powershell
notepad $env:USERPROFILE\.ssh\known_hosts
```

Check whether the host has an existing entry and investigate any fingerprint mismatch before changing it.

### 4. Python module not found

Activate the virtual environment and reinstall the dependencies:

```powershell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 5. File transfer failed

Check:

- Remote file permissions.
- Remote directory permissions.
- Local file path.
- Available disk space.
- SFTP access for the remote account.

---

## Project Structure

The repository may contain the following modules as the project evolves:

```text
RemoteOpsAI/
│
├── server.py
├── config.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── managers/                     # all *_manager.py modules (Python package)
│   ├── host_manager.py
│   ├── ssh_manager.py
│   ├── sftp_manager.py
│   ├── ftp_manager.py
│   ├── linux_system_manager.py
│   ├── linux_manager.py
│   ├── java_manager.py
│   ├── java_application_manager.py
│   ├── database_manager.py
│   ├── legacy_database_manager.py
│   ├── certificate_manager.py
│   └── docker_manager.py
│
├── uploads/
├── downloads/
└── .venv/
```

All manager modules live in the `managers/` package; import them as `from managers import <name>` (or `from managers.<name> import ...`). `config.py` stays at the project root and is imported by the managers, so start the server as `python server.py` (as configured in VS Code).

---

## Future Enhancements

Planned improvements include:

- Advanced Linux diagnostics.
- Java and JVM troubleshooting.
- JBoss EAP and WildFly diagnostics.
- PostgreSQL and MySQL troubleshooting.
- SSL/TLS certificate discovery and inspection.
- Java keystore inspection.
- Application deployment automation.
- Deployment verification and rollback.
- AI-assisted application log analysis.
- Multi-host session isolation.
- Secure centralized HTTP-based MCP hosting.
- Reusable Copilot Agent Skills for common operational workflows.

---

## Technology Stack

- Python
- Model Context Protocol (MCP)
- Paramiko
- SSH
- SFTP
- Linux
- GitHub Copilot
- Visual Studio Code

---

## Contributing

Contributions, bug reports, and feature suggestions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make your changes.
4. Test the MCP tools.
5. Submit a pull request.

Please do not include real server credentials, private keys, production logs containing secrets, or sensitive infrastructure details in issues or pull requests.

---

## License

RemoteOpsAI is licensed under the [MIT License](LICENSE).

---

**RemoteOpsAI — Manage remote Linux infrastructure through natural language.**
