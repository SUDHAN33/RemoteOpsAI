
"""RemoteOpsAI password-based SSH host manager."""

import json
from pathlib import Path
import re
import paramiko
from pathlib import Path
from threading import Lock

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
HOSTS_FILE = DATA_DIR / "hosts.json"
ACTIVE_FILE = DATA_DIR / "active_host.txt"

# Passwords exist only in MCP process memory.
# They are never written to hosts.json.
_SESSION_PASSWORDS = {}

# Windows SSH known_hosts location
KNOWN_HOSTS_FILE = Path.home() / ".ssh" / "known_hosts"

# Protect known_hosts writes from simultaneous connections
_known_hosts_lock = Lock()


class SaveNewHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """
    Automatically saves an unknown SSH host key
    to the local known_hosts file.

    Existing host keys are still verified by Paramiko.
    Changed or mismatched keys are rejected.
    """

    def missing_host_key(self, client, hostname, key):

        with _known_hosts_lock:

            # Save the newly discovered host key
            client.get_host_keys().add(
                hostname,
                key.get_name(),
                key
            )

            # Persist the key to known_hosts
            client.save_host_keys(str(KNOWN_HOSTS_FILE))

            print(
                f"[RemoteOpsAI] New SSH host key saved: "
                f"{hostname} ({key.get_name()})"
            )

def _ensure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not HOSTS_FILE.exists():
        HOSTS_FILE.write_text("{}", encoding="utf-8")


def _load():
    _ensure()
    return json.loads(HOSTS_FILE.read_text(encoding="utf-8"))


def _save(data):
    _ensure()
    HOSTS_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )


def validate_host_name(name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name or ""):
        raise ValueError("Invalid host profile name.")

    return name


def add_host_profile(
    name,
    hostname,
    username,
    port=22,
    base_dir="/home"
):
    """Save connection details without saving the password."""

    name = validate_host_name(name)

    if not hostname or not username:
        raise ValueError("Hostname and username are required.")

    if not 1 <= int(port) <= 65535:
        raise ValueError("Invalid SSH port.")

    if not base_dir.startswith("/") or ".." in Path(base_dir).parts:
        raise ValueError("Invalid remote base directory.")

    data = _load()

    data[name] = {
        "hostname": hostname,
        "username": username,
        "port": int(port),
        "base_dir": base_dir
    }

    _save(data)

    return f"Host profile '{name}' saved. Password not stored."


def list_host_profiles():
    data = _load()

    if not data:
        return "No remote hosts configured."

    return "\n".join(
        f"{name}: {p['username']}@{p['hostname']}:{p['port']}"
        for name, p in data.items()
    )


def set_active_host(name):
    name = validate_host_name(name)

    if name not in _load():
        raise ValueError(f"Host profile '{name}' does not exist.")

    ACTIVE_FILE.write_text(name, encoding="utf-8")

    return f"Active host changed to '{name}'."


def get_active_profile():
    _ensure()

    if not ACTIVE_FILE.exists():
        raise RuntimeError("No active remote host selected.")

    name = ACTIVE_FILE.read_text(encoding="utf-8").strip()
    profile = _load().get(name)

    if not profile:
        raise RuntimeError("Active host profile not found.")

    profile = dict(profile)
    profile["profile_name"] = name

    return profile


def connect_to_host(name, hostname, username, password,
                    port=22, base_dir="/home"):
    """
    Register and connect to a remote server using password authentication.
    Password remains in process memory only.
    """

    if not password:
        raise ValueError("SSH password is required.")

    add_host_profile(
        name=name,
        hostname=hostname,
        username=username,
        port=port,
        base_dir=base_dir
    )

    # Activate this host.
    set_active_host(name)

    _SESSION_PASSWORDS[name] = password

    # Verify the connection immediately.
    client = connect_active_host()

    try:
        return (
            f"SSH connection successful!\n"
            f"Profile: {name}\n"
            f"Host: {hostname}\n"
            f"Username: {username}\n"
            f"Authentication: Password\n"
            f"Connection status: Active"
        )
    finally:
        client.close()


def connect_active_host():

    profile = get_active_profile()

    if not profile:
        raise RuntimeError("No active remote host selected.")

    name = profile["profile_name"]
    password = _SESSION_PASSWORDS.get(name)

    if not password:
        raise RuntimeError(
            f"No cached password for profile '{name}'. "
            "Reconnect using connect_remote_host."
        )

    # Create SSH directory if it does not exist
    KNOWN_HOSTS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # Create known_hosts file if it does not exist
    KNOWN_HOSTS_FILE.touch(exist_ok=True)

    client = paramiko.SSHClient()

    try:

        # Load globally trusted SSH host keys
        client.load_system_host_keys()

        # Load writable known_hosts entries
        client.load_host_keys(str(KNOWN_HOSTS_FILE))

        # Automatically save previously unknown host keys
        client.set_missing_host_key_policy(
            SaveNewHostKeyPolicy()
        )

        client.connect(
            hostname=profile["hostname"],
            port=profile.get("port", 22),
            username=profile["username"],
            password=password,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
            allow_agent=False,
            look_for_keys=False
        )

        return client

    except Exception:
        client.close()
        raise


def get_active_host_summary():
    profile = get_active_profile()

    return (
        f"Active profile: {profile['profile_name']}\n"
        f"Host: {profile['hostname']}\n"
        f"Username: {profile['username']}\n"
        f"Port: {profile['port']}\n"
        f"Base directory: {profile['base_dir']}"
    )


def disconnect_host(name):
    """Forget the password held in process memory."""

    name = validate_host_name(name)
    _SESSION_PASSWORDS.pop(name, None)

    return f"Password session cleared for '{name}'."
