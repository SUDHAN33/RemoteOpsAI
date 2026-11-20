"""Named-host Java truststore and HTTP diagnostics."""
import base64
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import ipaddress
from pathlib import PurePosixPath
import re
import shlex
import struct
from urllib.parse import urlsplit

import paramiko

from .host_manager import connect_host


@dataclass
class _JavaTLS:
    pid: int
    executable: str
    truststore: str
    store_type: str | None
    password: str | None = field(repr=False)
    bind_address: str | None = None

    def summary(self) -> dict:
        return {
            "pid": self.pid,
            "java_executable": self.executable,
            "truststore": self.truststore,
            "truststore_type_property": self.store_type,
            "password_configured": self.password is not None,
            "jboss_bind_address": self.bind_address,
        }


def _run(
    client: paramiko.SSHClient, args: list[str], data: bytes | None = None,
    timeout: int = 30,
) -> tuple[str, str]:
    command = shlex.join(args)
    if data is None:
        command += " < /dev/null"
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if data is not None:
        stdin.write(data)
        stdin.flush()
        stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"{PurePosixPath(args[0]).name} failed ({code}):\n{err}{out}")
    return out, err


def _configuration(sftp: paramiko.SFTPClient, pid: int) -> _JavaTLS:
    if type(pid) is not int or pid <= 1:
        raise ValueError("pid must be an integer greater than 1.")
    root = f"/proc/{pid}"
    with sftp.open(root + "/cmdline", "rb") as stream:
        args = stream.read().decode("utf-8").rstrip("\x00").split("\x00")
    executable = sftp.readlink(root + "/exe")
    if PurePosixPath(executable).name != "java":
        raise ValueError(f"PID {pid} is not a Java executable.")
    properties = dict(arg[2:].split("=", 1) for arg in args if arg.startswith("-D") and "=" in arg)
    store = properties.get("javax.net.ssl.trustStore")
    if store == "NONE":
        raise ValueError("Non-file truststores (trustStore=NONE) are not supported.")
    if store is not None:
        if not store:
            raise ValueError("An empty javax.net.ssl.trustStore property cannot be inspected.")
        if not PurePosixPath(store).is_absolute():
            store = str(PurePosixPath(sftp.readlink(root + "/cwd")) / store)
        sftp.stat(store)
    else:
        java_home = properties.get("java.home", str(PurePosixPath(executable).parent.parent))
        security = PurePosixPath(java_home) / "lib" / "security"
        store = str(security / "jssecacerts")
        try:
            sftp.stat(store)
        except FileNotFoundError:
            store = str(security / "cacerts")
            sftp.stat(store)
    return _JavaTLS(
        pid, executable, store, properties.get("javax.net.ssl.trustStoreType"),
        properties.get("javax.net.ssl.trustStorePassword"),
        properties.get("jboss.bind.address"),
    )


def inspect_java_tls_configuration(profile_name: str, pid: int | None = None) -> dict:
    client = connect_host(profile_name)
    try:
        if pid is None:
            # Use a fixed search path because non-interactive SSH shells may have none.
            out, _ = _run(client, [
                "/bin/sh", "-c",
                "PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH; ps -eo pid=,comm=",
            ])
            pids = [int(parts[0]) for line in out.splitlines()
                    if len(parts := line.split()) == 2 and parts[1] == "java"]
            if not pids:
                raise RuntimeError("No Java processes found on the requested host.")
        else:
            pids = [pid]
        with client.open_sftp() as sftp:
            processes = [_configuration(sftp, process).summary() for process in pids]
        return {
            "profile": profile_name, "processes": processes,
            "scope": "Command-line JVM properties and default truststore paths; "
                     "application-defined SSL contexts or later property changes are not inspected.",
        }
    finally:
        client.close()


def _truststore(profile_name: str, pid: int) -> dict:
    client = connect_host(profile_name)
    try:
        digest = hashlib.sha256()
        with client.open_sftp() as sftp:
            config = _configuration(sftp, pid)
            with sftp.open(config.truststore, "rb") as stream:
                while chunk := stream.read(65536):
                    digest.update(chunk)
        args = [
            str(PurePosixPath(config.executable).parent / "keytool"),
            "-J-Duser.language=en", "-J-Duser.country=US",
            "-list", "-v", "-keystore", config.truststore,
        ]
        if config.store_type:
            args.extend(["-storetype", config.store_type])
        data = None
        if config.password is not None:
            if any(char in config.password for char in "\r\n\x00"):
                raise ValueError("keytool password input cannot contain line breaks or NUL.")
            args.extend(["-storepass:file", "/dev/stdin"])
            data = (config.password + "\n").encode("utf-8")
        out, err = _run(client, args, data)
        fingerprints = sorted(re.findall(r"SHA256:\s*((?:[0-9A-F]{2}:){31}[0-9A-F]{2})", out))
        if not fingerprints and "Your keystore contains 0 entries" not in out:
            raise RuntimeError("keytool returned no recognizable SHA256 certificate fingerprints.")
        return {
            "profile": profile_name, **config.summary(), "file_sha256": digest.hexdigest(),
            "certificate_count": len(fingerprints), "certificate_fingerprints": fingerprints,
            "integrity_verified": config.password is not None, "warnings": err.strip(),
        }
    finally:
        client.close()


def compare_java_truststores(
    first_profile: str, first_pid: int, second_profile: str, second_pid: int,
) -> dict:
    first = _truststore(first_profile, first_pid)
    second = _truststore(second_profile, second_pid)
    first_certs = Counter(first["certificate_fingerprints"])
    second_certs = Counter(second["certificate_fingerprints"])
    return {
        "identical_files": first["file_sha256"] == second["file_sha256"],
        "same_certificate_fingerprints": first_certs == second_certs,
        "certificates_only_in_first": list((first_certs - second_certs).elements()),
        "certificates_only_in_second": list((second_certs - first_certs).elements()),
        "first": first, "second": second,
    }


_PROBE_SOURCE = r"""
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import javax.net.ssl.HttpsURLConnection;

class RemoteOpsTlsProbe {
    static String read(DataInputStream in) throws IOException {
        int length = in.readInt();
        if (length < 0 || length > 1048576) throw new IOException("Invalid input length");
        byte[] bytes = in.readNBytes(length);
        if (bytes.length != length) throw new EOFException("Incomplete probe input");
        return new String(bytes, StandardCharsets.UTF_8);
    }
    static void emit(String key, String value) {
        System.out.println(key + "=" + Base64.getEncoder().encodeToString(
            value.getBytes(StandardCharsets.UTF_8)));
    }
    public static void main(String[] args) throws Exception {
        DataInputStream in = new DataInputStream(System.in);
        String url = read(in), store = read(in), password = read(in), type = read(in);
        boolean hasPassword = in.readBoolean();
        int timeout = in.readInt();
        System.setProperty("javax.net.ssl.trustStore", store);
        if (hasPassword) System.setProperty("javax.net.ssl.trustStorePassword", password);
        if (!type.isEmpty()) System.setProperty("javax.net.ssl.trustStoreType", type);
        HttpURLConnection connection = null;
        try {
            URL endpoint = URI.create(url).toURL();
            StringBuilder addresses = new StringBuilder();
            for (InetAddress address : InetAddress.getAllByName(endpoint.getHost())) {
                if (addresses.length() > 0) addresses.append(",");
                addresses.append(address.getHostAddress());
            }
            emit("resolved_addresses", addresses.toString());
            connection = (HttpURLConnection) endpoint.openConnection(Proxy.NO_PROXY);
            connection.setConnectTimeout(timeout);
            connection.setReadTimeout(timeout);
            connection.setInstanceFollowRedirects(false);
            int status = connection.getResponseCode();
            if (status < 100 || status > 599) throw new IOException("Invalid HTTP response status: " + status);
            emit("http_status", Integer.toString(status));
            if (connection instanceof HttpsURLConnection tls) {
                emit("cipher", tls.getCipherSuite());
                emit("peer_subject", tls.getPeerPrincipal().toString());
            }
            emit("status", "ok");
        } catch (IOException e) {
            emit("status", "error");
            emit("error_class", e.getClass().getName());
            emit("error", e.toString());
            StringBuilder causes = new StringBuilder();
            for (Throwable cause = e.getCause(); cause != null; cause = cause.getCause()) {
                causes.append(cause.toString()).append("\n");
            }
            emit("causes", causes.toString());
        } finally {
            if (connection != null) connection.disconnect();
        }
    }
}
"""


def _validate_endpoint(url: str, address_override: str | None) -> str:
    if any(ord(char) < 33 for char in url):
        raise ValueError("URL must not contain whitespace or control characters.")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Provide an absolute HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("URL credentials and fragments are not supported.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid URL port.")
    host = parsed.hostname
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        try:
            ipaddress.ip_address(host)
        except ValueError as error:
            raise ValueError("Provide an ASCII DNS hostname or IP address.") from error
    if address_override is not None:
        ipaddress.ip_address(address_override)
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("DNS overrides require a hostname URL, not an IP URL.")
    return host


def probe_java_http_connection(
    profile_name: str, pid: int, url: str, address_override: str | None = None,
    timeout_seconds: int = 6,
) -> dict:
    host = _validate_endpoint(url, address_override)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
        raise ValueError("timeout_seconds must be an integer between 1 and 30.")
    client = connect_host(profile_name)
    try:
        with client.open_sftp() as sftp:
            config = _configuration(sftp, pid)
            directory, _ = _run(client, ["/usr/bin/mktemp", "-d", "/tmp/remoteops-tls.XXXXXXXX"])
            directory = directory.strip()
            if not re.fullmatch(r"/tmp/remoteops-tls\.[A-Za-z0-9]+", directory):
                raise RuntimeError("mktemp did not return the expected temporary directory.")
            files: list[str] = []
            try:
                source_path = directory + "/RemoteOpsTlsProbe.java"
                files.append(source_path)
                with sftp.open(source_path, "w") as stream:
                    stream.write(_PROBE_SOURCE)
                args = [config.executable]
                if address_override is not None:
                    hosts_path = directory + "/hosts"
                    files.append(hosts_path)
                    with sftp.open(hosts_path, "w") as stream:
                        stream.write(f"127.0.0.1 localhost\n{address_override} {host}\n")
                    args.append("-Djdk.net.hosts.file=" + hosts_path)
                args.append(source_path)
                # The source and process arguments never contain credentials.
                data = b""
                for value in (url, config.truststore, config.password or "", config.store_type or ""):
                    encoded = value.encode("utf-8")
                    data += struct.pack(">i", len(encoded)) + encoded
                data += struct.pack(">?i", config.password is not None, timeout_seconds * 1000)
                out, err = _run(client, args, data, timeout=90)
            finally:
                cleanup_errors = []
                for path in reversed(files):
                    try:
                        sftp.remove(path)
                    except FileNotFoundError:
                        pass
                    except OSError as error:
                        cleanup_errors.append(f"{path}: {error}")
                try:
                    sftp.rmdir(directory)
                except OSError as error:
                    cleanup_errors.append(f"{directory}: {error}")
                if cleanup_errors:
                    raise RuntimeError("Probe temporary-file cleanup failed: " + "; ".join(cleanup_errors))
        result = {}
        for line in out.splitlines():
            key, separator, value = line.partition("=")
            if not separator:
                raise RuntimeError("Unexpected Java probe output.")
            result[key] = base64.b64decode(value, validate=True).decode("utf-8")
        if result.get("status") not in ("ok", "error"):
            raise RuntimeError("Java probe returned no status.")
        if "http_status" in result:
            result["http_status"] = int(result["http_status"])
        return {
            "profile": profile_name, "pid": pid, "url": url,
            "address_override": address_override, "truststore": config.truststore,
            "certificate_validation": "enabled" if urlsplit(url).scheme == "https" else "not applicable",
            "result": result, "warnings": err.strip(),
            "scope": "Fresh JVM using the selected executable and command-line truststore settings; "
                     "direct GET, no redirects, no proxy, no client certificate.",
        }
    finally:
        client.close()
