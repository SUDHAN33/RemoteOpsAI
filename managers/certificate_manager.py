"""TLS endpoint, on-disk PEM certificate, and Java keystore inspection."""
import shlex
import socket
import ssl
from datetime import datetime, timezone
from pathlib import PurePosixPath
from .host_manager import connect_active_host, get_active_profile

def inspect_tls_endpoint(host: str, port: int = 443) -> str:
    if not host or len(host) > 253 or not (1 <= int(port) <= 65535):
        raise ValueError("Invalid host or port.")
    context = ssl.create_default_context()
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
            der = tls.getpeercert(binary_form=True)
            import hashlib
            not_after = cert.get("notAfter", "unknown")
            return (
                f"Endpoint: {host}:{port}\n"
                f"TLS version: {tls.version()}\n"
                f"Cipher: {tls.cipher()}\n"
                f"Subject: {cert.get('subject')}\n"
                f"Issuer: {cert.get('issuer')}\n"
                f"Subject Alt Names: {cert.get('subjectAltName')}\n"
                f"Not before: {cert.get('notBefore')}\n"
                f"Not after: {not_after}\n"
                f"SHA256 fingerprint: {hashlib.sha256(der).hexdigest()}"
            )

def inspect_remote_pem_certificate(relative_path: str) -> str:
    profile = get_active_profile()
    base = PurePosixPath(profile.get("certificate_dir", profile.get("base_dir", "/home")))
    rel = PurePosixPath(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Provide a relative path inside the configured certificate directory.")
    path = str(base / rel)
    client = connect_active_host()
    try:
        command = "openssl x509 -in " + shlex.quote(path) + " -noout -subject -issuer -serial -dates -fingerprint -sha256 -ext subjectAltName"
        _, stdout, stderr = client.exec_command(command, timeout=20)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return out if code == 0 else f"Certificate inspection failed: {err or out}"
    finally:
        client.close()

def inspect_remote_keystore(
    relative_path: str,
    store_password: str | None = None,
    alias: str | None = None,
    keytool_path: str = "keytool",
) -> str:
    profile = get_active_profile()
    base = PurePosixPath(profile.get("certificate_dir", profile.get("base_dir", "/home")))
    rel = PurePosixPath(relative_path)
    if not relative_path or rel == PurePosixPath(".") or rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Provide a relative keystore path inside the configured certificate directory.")
    if not keytool_path or "\x00" in keytool_path:
        raise ValueError("Provide the keytool executable name or path.")
    if store_password is not None and any(char in store_password for char in "\r\n\x00"):
        raise ValueError("Keystore password must not contain line breaks or NUL characters.")
    path = str(base / rel)
    args = [keytool_path, "-list", "-v", "-keystore", path]
    if alias is not None:
        if not alias or "\x00" in alias:
            raise ValueError("Provide a non-empty certificate alias without NUL characters.")
        args.extend(["-alias", alias])
    if store_password is not None:
        args.extend(["-storepass:file", "/dev/stdin"])
    command = shlex.join(args)
    if store_password is None:
        command += " < /dev/null"

    client = connect_active_host()
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=30)
        if store_password is not None:
            # Keep the password out of the remote command line and process list.
            stdin.write(store_password + "\n")
            stdin.flush()
            stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if code != 0:
            return f"Keystore inspection failed ({code}):\n{err}{out}"
        warning = (
            "Keystore integrity has NOT been verified (no store password supplied).\n"
            if store_password is None else ""
        )
        return f"Keystore: {path}\n{warning}{out}{err}"
    finally:
        client.close()

def list_remote_certificate_files(relative_directory: str = ".") -> str:
    profile = get_active_profile()
    base = PurePosixPath(profile.get("certificate_dir", profile.get("base_dir", "/home")))
    rel = PurePosixPath(relative_directory)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Invalid relative directory.")
    path = str(base / rel)
    client = connect_active_host()
    try:
        command = ("find " + shlex.quote(path) +
                   " -maxdepth 3 -type f \\( -iname '*.pem' -o -iname '*.crt' "
                   "-o -iname '*.cer' -o -iname '*.der' \\) -print 2>/dev/null | head -n 200")
        _, stdout, stderr = client.exec_command(command, timeout=25)
        out = stdout.read().decode("utf-8", "replace")
        return out or "No certificate files found in the configured directory."
    finally:
        client.close()
