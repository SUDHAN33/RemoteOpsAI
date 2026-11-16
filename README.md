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

### 3. Remote File Management (SFTP)
- List remote directories.
- Read remote files.
- Upload files from your local machine.
- Download files from remote servers.
- Create remote directories.

## RemoteOpsAI FTP / FTPS Add-on

**This add‑on introduces a dedicated FTP manager and a set of MCP tools for FTP/FTPS operations.** It works alongside the existing Paramiko‑based SSH/SFTP implementation without modifying it.

### Installation

1. Copy `ftp_manager.py` into the root of RemoteOpsAI, beside `server.py`.
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

### 4. Application and Infrastructure Troubleshooting

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
├── ssh_manager.py
├── sftp_manager.py
├── config.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── remoteops/
│   ├── host_manager.py
│   ├── linux_manager.py
│   ├── java_manager.py
│   ├── database_manager.py
│   └── certificate_manager.py
│
├── scripts/
│   └──
│
├── uploads/
├── downloads/
└── .venv/
```

The modules shown under `remoteops/` represent the intended modular architecture; include only files that are actually present in your repository.

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
