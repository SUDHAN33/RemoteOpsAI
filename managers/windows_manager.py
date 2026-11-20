"""Windows host management over PowerShell Remoting (WinRM / PSRP).

Mirrors the Linux tools: connect with a username and password, run commands,
read and transfer files inside a base directory, and collect diagnostics.
Passwords are held in process memory only and are never written to disk.
"""
import base64
import hashlib
import ipaddress
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from threading import Lock

from config import DOWNLOAD_DIR, UPLOAD_DIR
from .host_manager import DATA_DIR, validate_host_name

PROFILES_FILE = DATA_DIR / "windows_hosts.json"
ACTIVE_FILE = DATA_DIR / "active_windows_host.txt"

MAX_READ_BYTES = 1024 * 1024
MAX_TRANSFER_BYTES = 100 * 1024 * 1024
MAX_OUTPUT_CHARS = 60000
MAX_SCRIPT_CHARS = 100000
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DIRECTORY_LIMIT = 2000

_SESSION_PASSWORDS: dict[str, str] = {}
_profiles_lock = Lock()

_HOST_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
_SERVICE_RE = re.compile(r"[A-Za-z0-9_.@ -]{1,256}")
_INVALID_PATH_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_DEVICE_NAME = re.compile(
    r"(?i)(con|prn|aux|nul|com[0-9\u00b9\u00b2\u00b3]|lpt[0-9\u00b9\u00b2\u00b3]|conin\$|conout\$)(\..*)?"
)
_AUTH_METHODS = ("ntlm", "negotiate")


# ----------------------------------------------------------------------------
# Profiles
# ----------------------------------------------------------------------------

def _load_profiles() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not PROFILES_FILE.exists():
        return {}
    return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))


def _save_profiles(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _active_name() -> str:
    if not ACTIVE_FILE.exists():
        raise RuntimeError("No active Windows host. Use connect_windows_host first.")
    return ACTIVE_FILE.read_text(encoding="utf-8").strip()


def _validate_hostname(hostname: str) -> str:
    host = (hostname or "").strip()
    if _HOST_RE.fullmatch(host):
        return host
    try:
        ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("Provide an ASCII hostname or an IP address.") from error
    return host


def _check_component(part: str) -> None:
    if part != part.rstrip(" .") or part in ("", ".", ".."):
        raise ValueError(f"Invalid path component: {part!r}")
    if _DEVICE_NAME.fullmatch(part):
        raise ValueError(f"Reserved Windows device name is not allowed: {part!r}")


def normalize_base_dir(base_dir: str) -> str:
    match = re.fullmatch(r"([A-Za-z]):[\\/](.*)", base_dir or "", re.S)
    if not match or _INVALID_PATH_CHARS.search(match.group(2)):
        raise ValueError(r"base_dir must be an absolute local Windows path such as C:\ or C:\home\chp.")
    parts = [part for part in re.split(r"[\\/]+", match.group(2)) if part not in ("", ".")]
    for part in parts:
        _check_component(part)
    return str(PureWindowsPath(match.group(1).upper() + ":\\", *parts))


def resolve_path(base_dir: str, relative_path: str) -> str:
    """Resolve a relative path inside base_dir; reject escapes and unsafe names."""
    if relative_path is None or relative_path == "" or _INVALID_PATH_CHARS.search(relative_path):
        raise ValueError("Invalid remote path.")
    if relative_path[0] in "\\/":
        raise ValueError("Path must be relative to the configured base directory.")
    parts = [part for part in re.split(r"[\\/]+", relative_path) if part not in ("", ".")]
    for part in parts:
        _check_component(part)
    return str(PureWindowsPath(base_dir, *parts))


# ----------------------------------------------------------------------------
# Connection handling
# ----------------------------------------------------------------------------

def _explain(error: Exception, profile: dict) -> str:
    from pypsrp.exceptions import AuthenticationError, WSManFaultError, WinRMTransportError
    import requests

    text = str(error)
    endpoint = f"{profile['hostname']}:{profile['port']}"
    if isinstance(error, AuthenticationError) or (
        isinstance(error, WinRMTransportError) and getattr(error, "code", None) == 401
    ):
        return (
            f"WinRM at {endpoint} rejected the credentials (HTTP 401). Use MACHINE\\user or DOMAIN\\user "
            "with the correct password, and avoid repeated attempts because they can lock the account. "
            "Also confirm the authentication method is enabled on the host."
        )
    if isinstance(error, WSManFaultError) and ("Access is denied" in text or "AccessDenied" in text):
        return (
            f"The credentials were accepted by {endpoint}, but the account is not authorized for "
            "PowerShell Remoting. An administrator must add it to the Administrators or "
            "Remote Management Users group on the Windows host."
        )
    if isinstance(error, requests.exceptions.SSLError):
        return (
            f"TLS certificate validation failed for {endpoint}: {text}. Certificate validation is never "
            "disabled; install the issuing CA or pass ca_bundle_path with its PEM file."
        )
    if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return (
            f"Cannot reach WinRM at {endpoint}. Check that the WinRM service is running "
            "(Enable-PSRemoting), the firewall allows the port, and the hostname resolves."
        )
    return f"{type(error).__name__}: {text}"


def _open_client(profile: dict, password: str):
    try:
        from pypsrp.client import Client
    except ImportError as error:
        raise RuntimeError("The 'pypsrp' package is required. Run: pip install pypsrp") from error
    https = bool(profile.get("use_https"))
    return Client(
        profile["hostname"],
        username=profile["username"],
        password=password,
        port=int(profile["port"]),
        ssl=https,
        auth=profile.get("auth", "ntlm"),
        cert_validation=profile.get("ca_bundle") or True,
        encryption="auto" if https else "always",
        connection_timeout=15,
        operation_timeout=20,
        read_timeout=30,
        no_proxy=True,
    )


class _Connection:
    def __init__(self, profile: dict, password: str):
        self.profile = profile
        self.client = _open_client(profile, password)

    def close(self) -> None:
        self.client.close()

    @contextmanager
    def translated(self):
        """Convert transport failures into actionable messages."""
        try:
            yield
        except (ValueError, TimeoutError, RuntimeError, FileExistsError, FileNotFoundError):
            raise
        except Exception as error:
            raise RuntimeError(_explain(error, self.profile)) from error

    def invoke(self, script: str, *arguments, timeout: int = 60, pool=None) -> str:
        """Run a PowerShell script with positional arguments and return its text output."""
        from pypsrp.complex_objects import PSInvocationState
        from pypsrp.powershell import PowerShell, RunspacePool

        def execute(active_pool) -> str:
            shell = PowerShell(active_pool)
            shell.add_script(script)
            for argument in arguments:
                shell.add_argument(argument)
            shell.begin_invoke()
            deadline = time.monotonic() + timeout
            while shell.state == PSInvocationState.RUNNING:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    shell.stop()
                    raise TimeoutError(f"The operation exceeded {timeout} seconds and was stopped.")
                shell.poll_invoke(timeout=max(1, min(20, int(remaining))))
            if shell.had_errors:
                messages = [str(error) for error in shell.streams.error]
                raise RuntimeError("; ".join(messages) or "The remote script failed.")
            return "".join(str(item) for item in shell.output)

        with self.translated():
            if pool is not None:
                return execute(pool)
            with RunspacePool(self.client.wsman) as new_pool:
                return execute(new_pool)

    def json(self, script: str, *arguments, timeout: int = 60, pool=None) -> dict:
        return json.loads(self.invoke(script, *arguments, timeout=timeout, pool=pool))

    @contextmanager
    def pool(self):
        from pypsrp.powershell import RunspacePool

        with self.translated():
            with RunspacePool(self.client.wsman) as pool:
                yield pool


@contextmanager
def _connect(profile_name: str = ""):
    name = validate_host_name(profile_name or _active_name())
    profile = _load_profiles().get(name)
    if not profile:
        raise RuntimeError(f"Windows host profile '{name}' does not exist.")
    password = _SESSION_PASSWORDS.get(name)
    if not password:
        raise RuntimeError(
            f"No cached password for Windows profile '{name}'. Reconnect using connect_windows_host."
        )
    connection = _Connection(dict(profile, profile_name=name), password)
    try:
        yield connection
    finally:
        connection.close()


def connect_windows_host(
    name: str, hostname: str, username: str, password: str, port: int = 0,
    use_https: bool = False, base_dir: str = "C:\\", authentication: str = "ntlm",
    ca_bundle_path: str = "",
) -> str:
    name = validate_host_name(name)
    hostname = _validate_hostname(hostname)
    if not username or len(username) > 256 or any(ord(char) < 32 for char in username):
        raise ValueError("Provide a username such as MACHINE\\user or DOMAIN\\user.")
    if not password or "\x00" in password:
        raise ValueError("A Windows password is required.")
    port = int(port) or (5986 if use_https else 5985)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid WinRM port.")
    authentication = (authentication or "ntlm").lower()
    if authentication not in _AUTH_METHODS:
        raise ValueError("authentication must be 'ntlm' or 'negotiate'.")
    if ca_bundle_path:
        if not use_https:
            raise ValueError("ca_bundle_path applies only to HTTPS connections.")
        if not Path(ca_bundle_path).is_file():
            raise ValueError("ca_bundle_path must be an existing local PEM file.")
    profile = {
        "hostname": hostname, "username": username, "port": port, "use_https": bool(use_https),
        "base_dir": normalize_base_dir(base_dir), "auth": authentication,
    }
    if ca_bundle_path:
        profile["ca_bundle"] = str(Path(ca_bundle_path).resolve())

    connection = _Connection(dict(profile, profile_name=name), password)
    try:
        identity = connection.json(_VERIFY_SCRIPT, timeout=45)
    finally:
        connection.close()

    with _profiles_lock:
        profiles = _load_profiles()
        profiles[name] = profile
        _save_profiles(profiles)
        ACTIVE_FILE.write_text(name, encoding="utf-8")
    _SESSION_PASSWORDS[name] = password
    return (
        "Windows connection successful!\n"
        f"Profile: {name}\n"
        f"Host: {identity['computer']} ({hostname}:{port}, {'HTTPS' if use_https else 'HTTP with message encryption'})\n"
        f"Connected as: {identity['user']}\n"
        f"PowerShell: {identity['powershell']}\n"
        f"Base directory: {profile['base_dir']}\n"
        "This profile is now the active Windows host. The password is kept in memory only."
    )


def list_windows_hosts() -> str:
    profiles = _load_profiles()
    if not profiles:
        return "No Windows hosts configured."
    try:
        active = _active_name()
    except RuntimeError:
        active = ""
    return "\n".join(
        f"{'*' if name == active else ' '} {name}: {p['username']}@{p['hostname']}:{p['port']} "
        f"({'HTTPS' if p.get('use_https') else 'HTTP'}, base {p['base_dir']}, "
        f"password {'cached' if name in _SESSION_PASSWORDS else 'not cached'})"
        for name, p in profiles.items()
    )


def switch_windows_host(name: str) -> str:
    name = validate_host_name(name)
    if name not in _load_profiles():
        raise ValueError(f"Windows host profile '{name}' does not exist.")
    ACTIVE_FILE.write_text(name, encoding="utf-8")
    return f"Active Windows host changed to '{name}'."


def disconnect_windows_host(name: str) -> str:
    name = validate_host_name(name)
    _SESSION_PASSWORDS.pop(name, None)
    return f"Password session cleared for Windows profile '{name}'."


def verify_windows_connection(profile_name: str = "") -> str:
    with _connect(profile_name) as connection:
        identity = connection.json(_VERIFY_SCRIPT, timeout=45)
        profile = connection.profile
    return (
        "Windows connection verified.\n"
        f"Profile: {profile['profile_name']}\n"
        f"Host: {identity['computer']} ({profile['hostname']}:{profile['port']})\n"
        f"Connected as: {identity['user']}\n"
        f"PowerShell: {identity['powershell']}"
    )


# ----------------------------------------------------------------------------
# Remote scripts. Every value is passed as an argument, never interpolated.
# ----------------------------------------------------------------------------

_PRELUDE = r"""
function Resolve-Safe([string]$BasePath, [string]$Candidate) {
    $root = [IO.Path]::GetFullPath($BasePath).TrimEnd('\')
    $full = [IO.Path]::GetFullPath($Candidate)
    $inside = $full.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)
    if (-not $inside) { throw "Path escapes the configured base directory: $full" }
    $cursor = $full
    while ($cursor -and $cursor.Length -gt $root.Length) {
        if ((Test-Path -LiteralPath $cursor) -and
            ([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Path passes through a reparse point (junction or symbolic link): $cursor"
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $full
}
function Open-SharedRead([string]$FilePath) {
    return New-Object IO.FileStream($FilePath, [IO.FileMode]::Open, [IO.FileAccess]::Read,
        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
}
function Get-Sha256Hex([string]$FilePath) {
    $stream = Open-SharedRead $FilePath
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $sha.Dispose() }
    } finally { $stream.Dispose() }
}
function ConvertTo-Result($Value) { return ConvertTo-Json -InputObject $Value -Depth 5 -Compress }
"""

_VERIFY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
ConvertTo-Json -Compress -InputObject ([ordered]@{
    computer = $env:COMPUTERNAME
    user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    powershell = $PSVersionTable.PSVersion.ToString()
})
"""

_LIST_SCRIPT = """param([string]$Base, [string]$Path, [int]$Limit)
$ErrorActionPreference = 'Stop'
#PRELUDE
$full = Resolve-Safe $Base $Path
if (-not [IO.Directory]::Exists($full)) { throw "Directory not found: $full" }
$entries = New-Object System.Collections.ArrayList
$truncated = $false
foreach ($entry in (New-Object IO.DirectoryInfo($full)).EnumerateFileSystemInfos()) {
    if ($entries.Count -ge $Limit) { $truncated = $true; break }
    $isDir = [bool]($entry.Attributes -band [IO.FileAttributes]::Directory)
    [void]$entries.Add([ordered]@{
        name = $entry.Name
        type = $(if ($isDir) { 'DIR' } else { 'FILE' })
        size = $(if ($isDir) { 0 } else { $entry.Length })
    })
}
ConvertTo-Result ([ordered]@{ path = $full; truncated = $truncated; entries = @($entries) })
""".replace("#PRELUDE", _PRELUDE)

_READ_SCRIPT = """param([string]$Base, [string]$Path, [int]$MaxBytes)
$ErrorActionPreference = 'Stop'
#PRELUDE
$full = Resolve-Safe $Base $Path
if (-not [IO.File]::Exists($full)) { throw "File not found: $full" }
$stream = Open-SharedRead $full
try {
    if ($stream.Length -gt $MaxBytes) { throw "File exceeds the 1 MB reading limit" }
    $buffer = New-Object byte[] ([int]$stream.Length)
    $read = 0
    while ($read -lt $buffer.Length) {
        $count = $stream.Read($buffer, $read, $buffer.Length - $read)
        if ($count -le 0) { break }
        $read += $count
    }
} finally { $stream.Dispose() }
ConvertTo-Result ([ordered]@{ path = $full; size = $read; content = [Convert]::ToBase64String($buffer, 0, $read) })
""".replace("#PRELUDE", _PRELUDE)

_MKDIR_SCRIPT = """param([string]$Base, [string]$Path)
$ErrorActionPreference = 'Stop'
#PRELUDE
$full = Resolve-Safe $Base $Path
if ([IO.Directory]::Exists($full) -or [IO.File]::Exists($full)) { throw "Path already exists: $full" }
$parent = [IO.Path]::GetDirectoryName($full)
if (-not [IO.Directory]::Exists($parent)) { throw "Parent directory does not exist: $parent" }
[void][IO.Directory]::CreateDirectory($full)
ConvertTo-Result ([ordered]@{ path = $full })
""".replace("#PRELUDE", _PRELUDE)

_UPLOAD_PREPARE_SCRIPT = """param([string]$Base, [string]$Path)
$ErrorActionPreference = 'Stop'
#PRELUDE
$full = Resolve-Safe $Base $Path
if ([IO.Directory]::Exists($full) -or [IO.File]::Exists($full)) {
    throw "Remote destination exists. Choose another filename."
}
$parent = [IO.Path]::GetDirectoryName($full)
if (-not [IO.Directory]::Exists($parent)) { throw "Parent directory does not exist: $parent" }
$temp = [IO.Path]::Combine($parent, '.remoteops-' + [guid]::NewGuid().ToString('N') + '.part')
ConvertTo-Result ([ordered]@{ path = $full; temp = $temp })
""".replace("#PRELUDE", _PRELUDE)

_UPLOAD_FINISH_SCRIPT = """param([string]$Base, [string]$Temp, [string]$Destination, [string]$Sha256)
$ErrorActionPreference = 'Stop'
#PRELUDE
$source = Resolve-Safe $Base $Temp
$target = Resolve-Safe $Base $Destination
try {
    if ((Get-Sha256Hex $source) -ne $Sha256.ToLowerInvariant()) { throw "Uploaded file checksum mismatch." }
    [IO.File]::Move($source, $target)
} catch {
    Remove-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue
    throw
}
ConvertTo-Result ([ordered]@{ path = $target })
""".replace("#PRELUDE", _PRELUDE)

_UPLOAD_CLEANUP_SCRIPT = """param([string]$Base, [string]$Temp)
$ErrorActionPreference = 'Stop'
#PRELUDE
$source = Resolve-Safe $Base $Temp
if ([IO.File]::Exists($source)) { Remove-Item -LiteralPath $source -Force }
""".replace("#PRELUDE", _PRELUDE)

_DOWNLOAD_PREPARE_SCRIPT = """param([string]$Base, [string]$Path, [int]$MaxBytes)
$ErrorActionPreference = 'Stop'
#PRELUDE
$full = Resolve-Safe $Base $Path
if (-not [IO.File]::Exists($full)) { throw "File not found: $full" }
$size = (New-Object IO.FileInfo($full)).Length
if ($size -gt $MaxBytes) { throw "Download exceeds the 100 MB limit" }
ConvertTo-Result ([ordered]@{ path = $full; size = $size; sha256 = (Get-Sha256Hex $full) })
""".replace("#PRELUDE", _PRELUDE)

_DOWNLOAD_CHUNK_SCRIPT = """param([string]$Base, [string]$Path, [int]$Offset, [int]$Count)
$ErrorActionPreference = 'Stop'
#PRELUDE
$full = Resolve-Safe $Base $Path
$stream = Open-SharedRead $full
try {
    [void]$stream.Seek($Offset, [IO.SeekOrigin]::Begin)
    $buffer = New-Object byte[] $Count
    $read = 0
    while ($read -lt $Count) {
        $n = $stream.Read($buffer, $read, $Count - $read)
        if ($n -le 0) { break }
        $read += $n
    }
} finally { $stream.Dispose() }
[Convert]::ToBase64String($buffer, 0, $read)
""".replace("#PRELUDE", _PRELUDE)

_POWERSHELL_SCRIPT = """param([string]$Base, [string]$Path, [string]$UserScript, [int]$MaxChars)
$ErrorActionPreference = 'Stop'
#PRELUDE
$cwd = Resolve-Safe $Base $Path
if (-not [IO.Directory]::Exists($cwd)) { throw "Working directory not found: $cwd" }
Set-Location -LiteralPath $cwd
$ErrorActionPreference = 'Continue'
$global:LASTEXITCODE = $null
$failed = $false
$errorCount = 0
try {
    $block = [scriptblock]::Create($UserScript)
    $items = @(& $block *>&1)
    $errorCount = @($items | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] }).Count
    $text = ($items | Out-String -Width 4096)
} catch {
    $failed = $true
    $text = ($_ | Out-String -Width 4096)
}
if ($null -eq $text) { $text = '' }
$truncated = $false
if ($text.Length -gt $MaxChars) { $text = $text.Substring(0, $MaxChars); $truncated = $true }
ConvertTo-Result ([ordered]@{
    failed = $failed; error_count = $errorCount; exit_code = $global:LASTEXITCODE
    truncated = $truncated; output = $text
})
""".replace("#PRELUDE", _PRELUDE)

_COMMAND_SCRIPT = """param([string]$Base, [string]$Path, [string]$Command, [int]$TimeoutSec, [int]$MaxChars)
$ErrorActionPreference = 'Stop'
#PRELUDE
$cwd = Resolve-Safe $Base $Path
if (-not [IO.Directory]::Exists($cwd)) { throw "Working directory not found: $cwd" }
$oem = [Text.Encoding]::GetEncoding([Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
$info = New-Object Diagnostics.ProcessStartInfo
$info.FileName = $env:ComSpec
$info.Arguments = '/d /s /c "' + $Command + '"'
$info.WorkingDirectory = $cwd
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardInput = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$info.StandardOutputEncoding = $oem
$info.StandardErrorEncoding = $oem
$process = [Diagnostics.Process]::Start($info)
$process.StandardInput.Close()
$stdout = $process.StandardOutput.ReadToEndAsync()
$stderr = $process.StandardError.ReadToEndAsync()
$timedOut = $false
$treeKilled = $false
if (-not $process.WaitForExit($TimeoutSec * 1000)) {
    $timedOut = $true
    # taskkill /T needs WMI; without it only the cmd.exe process itself can be terminated.
    $ErrorActionPreference = 'Continue'
    $null = & (Join-Path $env:SystemRoot 'System32\\taskkill.exe') /PID $process.Id /T /F 2>&1
    $treeKilled = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = 'Stop'
    if (-not $treeKilled -and -not $process.HasExited) { try { $process.Kill() } catch { } }
    [void]$process.WaitForExit(5000)
}
[void]$stdout.Wait(5000)
[void]$stderr.Wait(5000)
$out = $(if ($stdout.IsCompleted) { $stdout.Result } else { '' })
$err = $(if ($stderr.IsCompleted) { $stderr.Result } else { '' })
$truncated = ($out.Length -gt $MaxChars) -or ($err.Length -gt $MaxChars)
if ($out.Length -gt $MaxChars) { $out = $out.Substring(0, $MaxChars) }
if ($err.Length -gt $MaxChars) { $err = $err.Substring(0, $MaxChars) }
ConvertTo-Result ([ordered]@{
    exit_code = $(if ($process.HasExited) { $process.ExitCode } else { $null })
    timed_out = $timedOut; tree_killed = $treeKilled; truncated = $truncated; stdout = $out; stderr = $err
})
""".replace("#PRELUDE", _PRELUDE)

# Diagnostics use registry, .NET and netstat so a non-administrator remoting user (for example a
# member of Remote Management Users) gets results. WMI/CIM detail is added when it is permitted.
_SYSTEM_PRELUDE = r"""
function Test-WmiAccess {
    try { [void](Get-CimInstance Win32_OperatingSystem -ErrorAction Stop); return $true } catch { return $false }
}
function Format-Span([TimeSpan]$Span) {
    return ('{0}d {1:00}:{2:00}:{3:00}' -f $Span.Days, $Span.Hours, $Span.Minutes, $Span.Seconds)
}
function Get-TickUptime {
    $ticks = [Environment]::TickCount
    if ($ticks -lt 0) { $ticks += 4294967296 }
    return [TimeSpan]::FromMilliseconds($ticks)
}
$WmiNote = 'Note: WMI/CIM access is denied for this account, so data comes from non-WMI sources and some details are unavailable. Use an administrator account for full detail.'
"""

_SYSTEM_BODIES = {
    "system_information": r"""
$ErrorActionPreference = 'Stop'
$nt = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$osName = [string]$nt.ProductName
if ([int]$nt.CurrentBuildNumber -ge 22000 -and $osName -like 'Windows 10*') { $osName = $osName -replace 'Windows 10', 'Windows 11' }
$info = [ordered]@{
    ComputerName = $env:COMPUTERNAME
    OperatingSystem = $osName
    Build = ('{0}.{1}' -f $nt.CurrentBuildNumber, $nt.UBR)
    Architecture = $env:PROCESSOR_ARCHITECTURE
    LogicalProcessors = $env:NUMBER_OF_PROCESSORS
}
$limited = -not (Test-WmiAccess)
if ($limited) {
    $info.Domain = [Environment]::UserDomainName
    $info.Uptime = (Format-Span (Get-TickUptime)) + ' (approximate)'
} else {
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem
    $info.Domain = $cs.Domain
    $info.Manufacturer = $cs.Manufacturer
    $info.Model = $cs.Model
    $info.LastBootTime = $os.LastBootUpTime
    $info.Uptime = Format-Span ((Get-Date) - $os.LastBootUpTime)
    $info.LoggedOnUser = $cs.UserName
}
$info.ConnectedAs = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$info.PowerShellVersion = $PSVersionTable.PSVersion.ToString()
$info.TimeZone = [TimeZoneInfo]::Local.Id
$text = [pscustomobject]$info | Format-List | Out-String -Width 250
if ($limited) { $text + "`n" + $WmiNote } else { $text }
""",
    "uptime": r"""
$ErrorActionPreference = 'Stop'
if (Test-WmiAccess) {
    $os = Get-CimInstance Win32_OperatingSystem
    [pscustomobject][ordered]@{
        LastBootTime = $os.LastBootUpTime
        Uptime = Format-Span ((Get-Date) - $os.LastBootUpTime)
    } | Format-List | Out-String -Width 250
} else {
    $span = Get-TickUptime
    $text = [pscustomobject][ordered]@{
        ApproximateLastBootTime = (Get-Date) - $span
        ApproximateUptime = Format-Span $span
    } | Format-List | Out-String -Width 250
    $text + "`nNote: derived from the system tick counter because WMI is denied for this account; it wraps after 49.7 days of uptime."
}
""",
    "cpu_usage": r"""
$ErrorActionPreference = 'Stop'
if (Test-WmiAccess) {
    Get-CimInstance Win32_Processor | ForEach-Object {
        [pscustomobject][ordered]@{
            Name = $_.Name.Trim(); Cores = $_.NumberOfCores; LogicalProcessors = $_.NumberOfLogicalProcessors
            MaxClockMHz = $_.MaxClockSpeed; LoadPercent = $_.LoadPercentage
        }
    } | Format-Table -AutoSize | Out-String -Width 250
} else {
    $reg = Get-ItemProperty 'HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0'
    [pscustomobject][ordered]@{
        Name = ([string]$reg.ProcessorNameString).Trim(); LogicalProcessors = $env:NUMBER_OF_PROCESSORS
        MaxClockMHz = $reg.'~MHz'
    } | Format-Table -AutoSize | Out-String -Width 250
}
try {
    $sample = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction Stop).CounterSamples[0].CookedValue
    'Total processor time (instantaneous): {0:N1}%' -f $sample
} catch { 'Instantaneous processor load is unavailable (' + $_.Exception.Message + '). See windows_processes for per-process CPU time.' }
""",
    "memory": r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName Microsoft.VisualBasic
$memory = New-Object Microsoft.VisualBasic.Devices.ComputerInfo
$total = [double]$memory.TotalPhysicalMemory / 1GB
$free = [double]$memory.AvailablePhysicalMemory / 1GB
$info = [ordered]@{
    TotalPhysicalGB = [math]::Round($total, 2); FreePhysicalGB = [math]::Round($free, 2)
    UsedPhysicalGB = [math]::Round($total - $free, 2)
    UsedPercent = [math]::Round(100 * ($total - $free) / $total, 1)
}
if (Test-WmiAccess) {
    $os = Get-CimInstance Win32_OperatingSystem
    $info.CommitLimitGB = [math]::Round($os.TotalVirtualMemorySize / 1MB, 2)
    $info.CommitAvailableGB = [math]::Round($os.FreeVirtualMemory / 1MB, 2)
}
[pscustomobject]$info | Format-List | Out-String -Width 250
""",
    "disk_usage": r"""
$ErrorActionPreference = 'Stop'
[IO.DriveInfo]::GetDrives() | Where-Object { $_.DriveType -eq 'Fixed' -and $_.IsReady } | ForEach-Object {
    [pscustomobject][ordered]@{
        Drive = $_.Name; Label = $_.VolumeLabel; FileSystem = $_.DriveFormat
        SizeGB = [math]::Round($_.TotalSize / 1GB, 2); FreeGB = [math]::Round($_.AvailableFreeSpace / 1GB, 2)
        FreePercent = $(if ($_.TotalSize) { [math]::Round(100 * $_.AvailableFreeSpace / $_.TotalSize, 1) } else { 0 })
    }
} | Format-Table -AutoSize | Out-String -Width 250
""",
    "processes": r"""
$ErrorActionPreference = 'Stop'
Get-Process | Sort-Object CPU -Descending | Select-Object -First 30 Id, ProcessName,
    @{ n = 'CPUSeconds'; e = { if ($null -ne $_.CPU) { [math]::Round($_.CPU, 1) } } },
    @{ n = 'MemoryMB'; e = { [math]::Round($_.WorkingSet64 / 1MB, 1) } },
    @{ n = 'Threads'; e = { $_.Threads.Count } } |
    Format-Table -AutoSize | Out-String -Width 250
""",
    "top_memory_processes": r"""
$ErrorActionPreference = 'Stop'
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 30 Id, ProcessName,
    @{ n = 'MemoryMB'; e = { [math]::Round($_.WorkingSet64 / 1MB, 1) } },
    @{ n = 'CPUSeconds'; e = { if ($null -ne $_.CPU) { [math]::Round($_.CPU, 1) } } } |
    Format-Table -AutoSize | Out-String -Width 250
""",
    "java_processes": r"""
$ErrorActionPreference = 'Stop'
if (Test-WmiAccess) {
    $pattern = '(?i)(\S*(?:password|passwd|pwd|secret|token|apikey)\S*=)\S+'
    $items = @(Get-CimInstance Win32_Process -Filter "Name='java.exe' OR Name='javaw.exe'" | ForEach-Object {
        [pscustomobject][ordered]@{
            ProcessId = $_.ProcessId; ParentProcessId = $_.ParentProcessId
            MemoryMB = [math]::Round($_.WorkingSetSize / 1MB, 1)
            CommandLine = [regex]::Replace([string]$_.CommandLine, $pattern, '$1********')
        }
    })
    if ($items.Count -eq 0) { 'No Java processes found.' } else { $items | Format-List | Out-String -Width 4000 }
} else {
    $items = @(Get-Process -Name java, javaw -ErrorAction SilentlyContinue | ForEach-Object {
        $path = $null
        try { $path = $_.Path } catch { }
        [pscustomobject][ordered]@{ ProcessId = $_.Id; MemoryMB = [math]::Round($_.WorkingSet64 / 1MB, 1); Path = $path }
    })
    if ($items.Count -eq 0) { 'No Java processes found.' }
    else { ($items | Format-List | Out-String -Width 4000) + "`nNote: command lines are unavailable because WMI is denied for this account." }
}
""",
    "listening_ports": r"""
$ErrorActionPreference = 'Stop'
$names = @{}
Get-Process | ForEach-Object { $names[[int]$_.Id] = $_.ProcessName }
function Split-Endpoint([string]$Endpoint) {
    $index = $Endpoint.LastIndexOf(':')
    return @($Endpoint.Substring(0, $index).Trim('[', ']'), [int]$Endpoint.Substring($index + 1))
}
$rows = foreach ($line in (netstat.exe -ano)) {
    $fields = @($line.Trim() -split '\s+')
    if ($fields[0] -eq 'TCP' -and $fields.Count -ge 5 -and $fields[2] -match ':0$') {
        $local = Split-Endpoint $fields[1]
        [pscustomobject][ordered]@{ Protocol = 'TCP'; LocalAddress = $local[0]; LocalPort = $local[1]
            PID = [int]$fields[4]; Process = $names[[int]$fields[4]] }
    } elseif ($fields[0] -eq 'UDP' -and $fields.Count -ge 4) {
        $local = Split-Endpoint $fields[1]
        [pscustomobject][ordered]@{ Protocol = 'UDP'; LocalAddress = $local[0]; LocalPort = $local[1]
            PID = [int]$fields[3]; Process = $names[[int]$fields[3]] }
    }
}
@($rows) | Sort-Object Protocol, LocalPort | Format-Table -AutoSize | Out-String -Width 250
""",
    "network_interfaces": r"""
$ErrorActionPreference = 'Stop'
[Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | ForEach-Object {
    $addresses = @($_.GetIPProperties().UnicastAddresses | ForEach-Object { '{0}/{1}' -f $_.Address, $_.PrefixLength })
    [pscustomobject][ordered]@{
        Name = $_.Name; Status = $_.OperationalStatus; Type = $_.NetworkInterfaceType
        SpeedMbps = $(if ($_.Speed -gt 0) { [math]::Round($_.Speed / 1e6) } else { $null })
        MacAddress = $_.GetPhysicalAddress().ToString(); Addresses = ($addresses -join ', ')
    }
} | Format-List | Out-String -Width 250
""",
}
_SYSTEM_SCRIPTS = {name: _SYSTEM_PRELUDE + body for name, body in _SYSTEM_BODIES.items()}

_SERVICE_SCRIPT = r"""param([string]$Name)
$ErrorActionPreference = 'Stop'
$service = $null
try { $service = Get-Service -Name $Name -ErrorAction Stop } catch { }
$config = Get-ItemProperty -LiteralPath ('Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\' + $Name) -ErrorAction SilentlyContinue
if (-not $service -and -not $config) { throw "Service not found: $Name" }
$startModes = @{ 0 = 'Boot'; 1 = 'System'; 2 = 'Automatic'; 3 = 'Manual'; 4 = 'Disabled' }
$info = [ordered]@{ Name = $Name }
if ($service) {
    $info.DisplayName = $service.DisplayName
    $info.Status = $service.Status
    $info.CanStop = $service.CanStop
    $info.DependentServices = (($service.DependentServices | ForEach-Object { $_.Name }) -join ', ')
} else {
    $info.DisplayName = $config.DisplayName
    $info.Status = 'Unavailable (the service control manager hides this service from the connected account)'
}
if ($config) {
    $info.StartMode = $startModes[[int]$config.Start]
    if ($config.Start -eq 2 -and $config.DelayedAutostart -eq 1) { $info.StartMode += ' (delayed)' }
    $info.Account = $config.ObjectName
    $info.Path = $config.ImagePath
}
[pscustomobject]$info | Format-List | Out-String -Width 250
"""


# ----------------------------------------------------------------------------
# Command execution
# ----------------------------------------------------------------------------

def _validate_script(script: str, label: str) -> str:
    if not script or not script.strip() or len(script) > MAX_SCRIPT_CHARS or "\x00" in script:
        raise ValueError(f"{label} must be 1-{MAX_SCRIPT_CHARS} characters and contain no NUL characters.")
    return script


def _validate_timeout(timeout_seconds: int) -> int:
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise ValueError("timeout_seconds must be an integer between 1 and 600.")
    return timeout_seconds


def run_powershell(script: str, working_directory: str = ".", timeout_seconds: int = 60,
                   profile_name: str = "") -> str:
    _validate_script(script, "script")
    _validate_timeout(timeout_seconds)
    with _connect(profile_name) as connection:
        cwd = resolve_path(connection.profile["base_dir"], working_directory)
        result = connection.json(
            _POWERSHELL_SCRIPT, connection.profile["base_dir"], cwd, script, MAX_OUTPUT_CHARS,
            timeout=timeout_seconds,
        )
    lines = [f"Succeeded: {not result['failed'] and not result['error_count']}"]
    if result["exit_code"] is not None:
        lines.append(f"Last native exit code: {result['exit_code']}")
    if result["error_count"]:
        lines.append(f"Error records in output: {result['error_count']}")
    if result["truncated"]:
        lines.append(f"Output truncated to {MAX_OUTPUT_CHARS} characters.")
    return "\n".join(lines) + "\n--- output ---\n" + result["output"].rstrip()


def run_command(command: str, working_directory: str = ".", timeout_seconds: int = 60,
                profile_name: str = "") -> str:
    _validate_script(command, "command")
    _validate_timeout(timeout_seconds)
    with _connect(profile_name) as connection:
        cwd = resolve_path(connection.profile["base_dir"], working_directory)
        result = connection.json(
            _COMMAND_SCRIPT, connection.profile["base_dir"], cwd, command, timeout_seconds,
            MAX_OUTPUT_CHARS, timeout=timeout_seconds + 30,
        )
    lines = [f"Exit code: {result['exit_code']}"]
    if result["timed_out"]:
        if result["tree_killed"]:
            lines.append(f"Timed out after {timeout_seconds} seconds; the process tree was terminated.")
        else:
            lines.append(
                f"Timed out after {timeout_seconds} seconds; cmd.exe was terminated, but child processes it "
                "started may still be running (terminating a process tree needs WMI access, which this "
                "account lacks). Output may be incomplete."
            )
    if result["truncated"]:
        lines.append(f"Output truncated to {MAX_OUTPUT_CHARS} characters per stream.")
    lines.append("--- stdout ---\n" + result["stdout"].rstrip())
    if result["stderr"].strip():
        lines.append("--- stderr ---\n" + result["stderr"].rstrip())
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# File operations (confined to the profile's base directory)
# ----------------------------------------------------------------------------

def list_directory(relative_path: str = ".", profile_name: str = "") -> str:
    with _connect(profile_name) as connection:
        base = connection.profile["base_dir"]
        result = connection.json(_LIST_SCRIPT, base, resolve_path(base, relative_path), DIRECTORY_LIMIT)
    if not result["entries"]:
        return "Directory is empty"
    entries = sorted(result["entries"], key=lambda e: (e["type"] != "DIR", e["name"].lower()))
    text = "\n".join(f"{e['type']} | {e['name']} | {e['size']} bytes" for e in entries)
    if result["truncated"]:
        text += f"\n(Listing truncated after {DIRECTORY_LIMIT} entries.)"
    return text


def _decode_text(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def read_file(relative_path: str, profile_name: str = "") -> str:
    with _connect(profile_name) as connection:
        base = connection.profile["base_dir"]
        result = connection.json(_READ_SCRIPT, base, resolve_path(base, relative_path), MAX_READ_BYTES)
    return _decode_text(base64.b64decode(result["content"]))


def create_directory(relative_path: str, profile_name: str = "") -> str:
    with _connect(profile_name) as connection:
        base = connection.profile["base_dir"]
        result = connection.json(_MKDIR_SCRIPT, base, resolve_path(base, relative_path))
    return f"Directory created: {result['path']}"


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload_file(filename: str, remote_relative_path: str, profile_name: str = "") -> str:
    """Upload a file from the local uploads directory without overwriting."""
    if Path(filename).name != filename or filename in ("", ".", ".."):
        raise ValueError("Provide only a filename from the uploads directory")
    local = UPLOAD_DIR / filename
    if not local.is_file():
        raise FileNotFoundError("File not found in uploads directory")
    if local.stat().st_size > MAX_TRANSFER_BYTES:
        raise ValueError("Upload exceeds the 100 MB limit")
    digest = _sha256_of(local)

    with _connect(profile_name) as connection:
        base = connection.profile["base_dir"]
        target = connection.json(_UPLOAD_PREPARE_SCRIPT, base, resolve_path(base, remote_relative_path))
        try:
            with connection.translated():
                connection.client.copy(str(local), target["temp"])
            connection.json(_UPLOAD_FINISH_SCRIPT, base, target["temp"], target["path"], digest)
        except BaseException:
            try:
                connection.invoke(_UPLOAD_CLEANUP_SCRIPT, base, target["temp"])
            except Exception:
                pass
            raise
    return f"Successfully uploaded {filename} to {target['path']} (SHA256 {digest})"


def download_file(relative_path: str, profile_name: str = "") -> str:
    """Download a file into the local downloads directory without overwriting."""
    with _connect(profile_name) as connection:
        base = connection.profile["base_dir"]
        remote = resolve_path(base, relative_path)
        filename = PureWindowsPath(remote).name
        if Path(filename).name != filename or filename in ("", ".", ".."):
            raise ValueError("Invalid filename")
        local = DOWNLOAD_DIR / filename
        if local.exists():
            raise FileExistsError("Local download already exists. Rename or move it first.")
        info = connection.json(_DOWNLOAD_PREPARE_SCRIPT, base, remote, MAX_TRANSFER_BYTES)

        handle, partial_name = tempfile.mkstemp(prefix=".remoteops-", suffix=".part", dir=DOWNLOAD_DIR)
        partial = Path(partial_name)
        try:
            digest = hashlib.sha256()
            received = 0
            with os.fdopen(handle, "wb") as output, connection.pool() as pool:
                while received < info["size"]:
                    count = min(DOWNLOAD_CHUNK_BYTES, info["size"] - received)
                    chunk = base64.b64decode(connection.invoke(
                        _DOWNLOAD_CHUNK_SCRIPT, base, remote, received, count, pool=pool,
                    ))
                    if not chunk:
                        raise RuntimeError("The remote file changed size during download.")
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
            if received != info["size"] or digest.hexdigest() != info["sha256"]:
                raise RuntimeError("Downloaded file does not match the remote file; it may have changed.")
            if local.exists():
                raise FileExistsError("Local download already exists. Rename or move it first.")
            os.rename(partial, local)
        finally:
            partial.unlink(missing_ok=True)
    return f"Downloaded successfully: {local} ({received} bytes, SHA256 {info['sha256']})"


# ----------------------------------------------------------------------------
# Diagnostics
# ----------------------------------------------------------------------------

def _system(name: str, profile_name: str = "") -> str:
    with _connect(profile_name) as connection:
        return connection.invoke(_SYSTEM_SCRIPTS[name], timeout=60).strip()


def system_information(profile_name: str = "") -> str:
    return _system("system_information", profile_name)


def uptime(profile_name: str = "") -> str:
    return _system("uptime", profile_name)


def cpu_usage(profile_name: str = "") -> str:
    return _system("cpu_usage", profile_name)


def memory(profile_name: str = "") -> str:
    return _system("memory", profile_name)


def disk_usage(profile_name: str = "") -> str:
    return _system("disk_usage", profile_name)


def processes(profile_name: str = "") -> str:
    return _system("processes", profile_name)


def top_memory_processes(profile_name: str = "") -> str:
    return _system("top_memory_processes", profile_name)


def java_processes(profile_name: str = "") -> str:
    return _system("java_processes", profile_name)


def listening_ports(profile_name: str = "") -> str:
    return _system("listening_ports", profile_name)


def network_interfaces(profile_name: str = "") -> str:
    return _system("network_interfaces", profile_name)


def service_status(service_name: str, profile_name: str = "") -> str:
    if not _SERVICE_RE.fullmatch(service_name or ""):
        raise ValueError("Invalid service name.")
    with _connect(profile_name) as connection:
        return connection.invoke(_SERVICE_SCRIPT, service_name, timeout=60).strip()
