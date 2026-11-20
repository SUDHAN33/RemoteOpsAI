---
name: windows-remote-administration
description: Connect to a Windows server with a username and password over PowerShell Remoting (WinRM), then run PowerShell/cmd commands, read and transfer files, and collect diagnostics with the same workflow as the Linux tools. Includes setup prerequisites and fixes for 401, access-denied and WMI-denied failures.
---

# Windows remote administration

Use the RemoteOpsAI `windows_*` MCP tools instead of ad hoc Python, `winrm` or PowerShell
scripts. They use PowerShell Remoting (WinRM/PSRP), not SSH, and never need an SSH server on
the Windows host. Never put credentials in this skill, in files, or in command lines.

## Workflow

1. Check reachability only if connecting fails (see Troubleshooting). Ports: WinRM HTTP 5985,
   HTTPS 5986. Remote Desktop (3389) is separate and does not imply WinRM works.
2. Call `connect_windows_host(name, hostname, username, password, base_dir=...)`.
   - Username must be `MACHINE\user` or `DOMAIN\user`. Confirm it from the user's RDP
     dialog or `whoami` on the host; a bare `Administrator` often fails.
   - `base_dir` is the absolute Windows directory the file tools are confined to
     (for example `C:\home\chp`). Default is `C:\`.
   - HTTP (default) uses NTLM with mandatory message encryption. For HTTPS set
     `use_https=true`; the certificate is always validated, and `ca_bundle_path` may name a
     local PEM file for a private CA.
   - Success makes the profile active. The password is kept in memory only; after an MCP
     restart reconnect. Profiles (no passwords) are stored in `data/windows_hosts.json`.
3. Omit `profile_name` to use the active profile, or pass it to target another one.
   `list_windows_hosts`, `switch_windows_host`, `verify_windows_connection` and
   `disconnect_windows_host` manage profiles.
4. Use the matching tool:

| Task | Linux tool | Windows tool |
|---|---|---|
| Connect / switch / list / verify / disconnect | `connect_remote_host` ... | `connect_windows_host`, `switch_windows_host`, `list_windows_hosts`, `verify_windows_connection`, `disconnect_windows_host` |
| Run a command | (docker exec only) | `windows_run_powershell`, `windows_run_command` |
| List / read / create | `list_remote_directory`, `read_remote_file_tool`, `create_remote_directory_tool` | `windows_list_directory`, `windows_read_file`, `windows_create_directory` |
| Upload / download | `upload_local_file_tool`, `download_remote_file_tool` | `windows_upload_file`, `windows_download_file` |
| System / uptime | `linux_os_information`, `get_server_uptime` | `windows_system_information`, `windows_uptime` |
| CPU / memory / disk | `linux_cpu_load`, `linux_memory`, `linux_disk_usage` | `windows_cpu_usage`, `windows_memory`, `windows_disk_usage` |
| Processes | `linux_processes`, `linux_top_memory_processes`, `linux_java_processes` | `windows_processes`, `windows_top_memory_processes`, `windows_java_processes` |
| Network / services | `linux_listening_ports`, `linux_network_interfaces`, `linux_service_status` | `windows_listening_ports`, `windows_network_interfaces`, `windows_service_status` |

## File tool rules

- Paths are relative to `base_dir`; both `/` and `\` work. Absolute paths, drive letters,
  `..`, alternate data streams (`:`), reserved device names and trailing dots/spaces are
  rejected. Existing directory junctions and symbolic links inside the base are refused.
- `windows_read_file` reads up to 1 MB and decodes UTF-8/UTF-16. Use
  `windows_run_powershell` with `Get-Content -Tail` for large logs.
- Uploads come from the local `uploads/` folder and downloads go to `downloads/`; transfers
  are limited to 100 MB, verified with SHA256, and never overwrite an existing file.
- If the user gives a full path such as `C:/home/chp/x`, strip the base directory and pass
  the relative remainder, or reconnect with a base that contains it.

## Command tools

`windows_run_powershell` and `windows_run_command` run arbitrary code with the connected
account's privileges and are **not** confined to `base_dir` (only the working directory is
resolved inside it). Review what you run, prefer read-only commands, and ask the user before
anything destructive. Output is truncated at 60,000 characters. Timeouts are 1-600 s.
`cmd` input is closed so commands cannot wait for a prompt. A timeout terminates `cmd.exe`;
child processes survive unless the account may use WMI. PowerShell merges all streams, and
`Succeeded: False` means a terminating or non-terminating error record was produced.

## Account permissions and limits

The account must be a local Administrator or a member of **Remote Management Users**
(plus whatever the application folders require). A non-administrator account works, but:

- WMI/CIM is denied, so diagnostics fall back to registry, .NET and `netstat` data. Outputs
  say so; uptime is then approximate (tick counter) and Java command lines are unavailable.
- `Get-Counter` and per-service status may be denied; the tools report this rather than fail.
- The classic WinRS `cmd` shell may be denied even when PowerShell Remoting works, which is
  why `windows_run_command` runs `cmd.exe` through PowerShell Remoting.

## Troubleshooting

| Symptom | Likely cause and action |
|---|---|
| Cannot reach WinRM / timeout | WinRM service stopped, firewall, or wrong host. On the host (as Administrator): `Enable-PSRemoting -Force`, then `Get-NetTCPConnection -LocalPort 5985 -State Listen`. |
| HTTP 401 / "rejected the credentials" | Wrong password or username format. Verify locally on the host with `runas /user:"MACHINE\user" cmd`. **Do not retry repeatedly**; failed attempts can lock the account. |
| Credentials accepted but "Access is denied" (HTTP 500) | Account lacks remoting rights. An administrator adds it: `Add-LocalGroupMember -SID 'S-1-5-32-580' -Member 'MACHINE\user'`. Only do this if the user authorizes it. |
| TLS validation failure | Install the issuing CA, or pass `ca_bundle_path`. Never disable validation. |
| `pypsrp` import error | `pip install pypsrp` in the project's virtual environment. |

Insecure shortcuts are out of scope: do not enable Basic authentication or
`AllowUnencrypted`, and do not disable certificate validation. Changes to the Windows host's
configuration, groups or firewall need explicit user authorization.
