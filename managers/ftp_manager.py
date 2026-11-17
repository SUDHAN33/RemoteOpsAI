from __future__ import annotations
import ftplib
import ssl
from pathlib import Path
from threading import RLock
from typing import Dict, Any

_sessions: Dict[str, ftplib.FTP] = {}
_profiles: Dict[str, Dict[str, Any]] = {}
_lock = RLock()


def _get_session(profile_name: str) -> ftplib.FTP:
    with _lock:
        ftp = _sessions.get(profile_name)
        if ftp is None:
            raise RuntimeError(f"No active FTP connection for '{profile_name}'. Call connect_ftp_server first.")
        try:
            ftp.voidcmd("NOOP")
        except Exception as exc:
            try: ftp.close()
            except Exception: pass
            _sessions.pop(profile_name, None)
            _profiles.pop(profile_name, None)
            raise RuntimeError(f"FTP connection '{profile_name}' is no longer active: {exc}") from exc
        return ftp


def connect(profile_name: str, hostname: str, username: str, password: str,
            port: int = 21, protocol: str = "FTP", timeout: int = 20,
            passive: bool = True) -> str:
    protocol = protocol.strip().upper()
    if protocol not in {"FTP", "FTPS"}:
        raise ValueError("protocol must be 'FTP' or 'FTPS'.")
    if not profile_name.strip() or not hostname.strip():
        raise ValueError("profile_name and hostname are required.")
    if not 1 <= int(port) <= 65535:
        raise ValueError("port must be between 1 and 65535.")
    disconnect(profile_name)
    ftp = (ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=timeout)
           if protocol == "FTPS" else ftplib.FTP(timeout=timeout))
    try:
        ftp.connect(hostname, int(port), timeout=timeout)
        ftp.login(username, password)
        if protocol == "FTPS":
            ftp.prot_p()  # Encrypt the data channel too.
        ftp.set_pasv(bool(passive))
        with _lock:
            _sessions[profile_name] = ftp
            _profiles[profile_name] = {
                "hostname": hostname, "port": int(port), "username": username,
                "protocol": protocol, "passive": bool(passive)
            }
        return (f"{protocol} connection successful.\nProfile: {profile_name}\n"
                f"Server: {hostname}:{port}\nUsername: {username}\n"
                f"Passive mode: {bool(passive)}\nRemote directory: {ftp.pwd()}")
    except Exception:
        try: ftp.close()
        except Exception: pass
        raise


def status(profile_name: str) -> str:
    ftp = _get_session(profile_name)
    p = _profiles[profile_name]
    return (f"Connected: yes\nProfile: {profile_name}\nServer: {p['hostname']}:{p['port']}\n"
            f"Protocol: {p['protocol']}\nRemote directory: {ftp.pwd()}")


def list_directory(profile_name: str, remote_path: str = ".") -> str:
    ftp = _get_session(profile_name)
    try:
        rows = [f"{facts.get('type','unknown'):10} {facts.get('size',''):>12} "
                f"{facts.get('modify',''):14} {name}"
                for name, facts in ftp.mlsd(remote_path)]
    except (ftplib.error_perm, AttributeError):
        rows = [str(x) for x in ftp.nlst(remote_path)]
    return "\n".join(rows) if rows else f"No entries found in {remote_path}."


def change_directory(profile_name: str, remote_path: str) -> str:
    ftp = _get_session(profile_name)
    ftp.cwd(remote_path)
    return f"Remote working directory: {ftp.pwd()}"


def upload_file(profile_name: str, local_path: str, remote_path: str) -> str:
    ftp = _get_session(profile_name)
    source = Path(local_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Local file does not exist: {source}")
    if not remote_path.strip():
        raise ValueError("remote_path cannot be empty.")
    with source.open("rb") as stream:
        ftp.storbinary(f"STOR {remote_path}", stream)
    return f"Uploaded '{source}' to '{remote_path}' using '{profile_name}'."


def download_file(profile_name: str, remote_path: str, local_path: str) -> str:
    ftp = _get_session(profile_name)
    dest = Path(local_path).expanduser()
    if dest.exists() and dest.is_dir():
        dest = dest / Path(remote_path).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as stream:
        ftp.retrbinary(f"RETR {remote_path}", stream.write)
    return f"Downloaded '{remote_path}' to '{dest}'."


def create_directory(profile_name: str, remote_path: str) -> str:
    return f"Created remote directory: {_get_session(profile_name).mkd(remote_path)}"


def delete_file(profile_name: str, remote_path: str) -> str:
    _get_session(profile_name).delete(remote_path)
    return f"Deleted remote file: {remote_path}"


def rename_file(profile_name: str, source_path: str, destination_path: str) -> str:
    _get_session(profile_name).rename(source_path, destination_path)
    return f"Renamed '{source_path}' to '{destination_path}'."


def disconnect(profile_name: str) -> str:
    with _lock:
        ftp = _sessions.pop(profile_name, None)
        _profiles.pop(profile_name, None)
    if ftp is None:
        return f"No FTP connection was active for '{profile_name}'."
    try: ftp.quit()
    except Exception:
        try: ftp.close()
        except Exception: pass
    return f"Disconnected FTP profile '{profile_name}'."
