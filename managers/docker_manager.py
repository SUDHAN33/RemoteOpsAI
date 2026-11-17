"""Docker and Docker Compose management for RemoteOpsAI.

Every function accepts target="remote" (Docker CLI over SSH on the active host)
or target="local" (Docker CLI on the machine running this MCP server).
User input is validated; local commands run without a shell and remote
commands are shell-quoted.
"""

import functools
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from .host_manager import connect_active_host, get_active_profile

MAX_OUTPUT = 60000
_MAX_CAPTURE = 4 * 1024 * 1024
_DEFAULT_TIMEOUT = 60
_LONG_TIMEOUT = 900

_CONTAINER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_IMAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,254}")
_SINCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:.+-]{0,39}")
_COMPOSE_FILE_RE = re.compile(r"[A-Za-z0-9_.-]+\.ya?ml")
_DOCKER_CMD_RE = re.compile(r"(sudo -n )?[A-Za-z0-9_./-]+")
_SENSITIVE_RE = re.compile(r"pass|secret|token|key|pwd|credential", re.I)

_COMPOSE_DEFAULTS = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
_COMPOSE_OVERRIDES = (
    "compose.override.yaml", "compose.override.yml",
    "docker-compose.override.yaml", "docker-compose.override.yml",
)


# ---------------------------------------------------------------- helpers

def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = f"Docker operation failed: {e}"
            if "active remote host" in str(e) or "cached password" in str(e):
                msg += "\nTip: connect to a host first, or pass target='local' to use local Docker."
            return msg
    return wrapper


def _check(value, regex, label):
    value = (value or "").strip()
    if not regex.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def _names(value, label="service name"):
    items = [p for p in re.split(r"[\s,]+", value or "") if p]
    return [_check(p, _CONTAINER_RE, label) for p in items]


def _positive(value, label, maximum=100000):
    value = int(value)
    if not 0 <= value <= maximum:
        raise ValueError(f"Invalid {label}: {value}")
    return value


def _clip(text, tail=False):
    if len(text) <= MAX_OUTPUT:
        return text
    if tail:
        return f"[output truncated, showing last {MAX_OUTPUT} characters]\n" + text[-MAX_OUTPUT:]
    return text[:MAX_OUTPUT] + f"\n[output truncated at {MAX_OUTPUT} characters]"


def _text(res, empty="Done.", tail=False):
    code, out, err = res
    combined = (out + ("\n" + err if err.strip() else "")).strip()
    if code != 0:
        return f"Docker command failed (exit {code}):\n{_clip(combined, tail)}"
    return _clip(combined, tail) or empty


def _redact_env(container):
    env = container.get("Config", {}).get("Env")
    if env:
        container["Config"]["Env"] = [
            f"{k}=***" if _SENSITIVE_RE.search(k) else item
            for item in env
            for k in [item.split("=", 1)[0]]
        ]
    return container


# ---------------------------------------------------------------- runners

class _LocalRunner:
    name = "local"

    def __init__(self):
        self.docker = shutil.which("docker")
        if not self.docker:
            raise RuntimeError("Docker CLI not found on PATH of the RemoteOpsAI process.")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, args, cwd=None, timeout=_DEFAULT_TIMEOUT):
        try:
            proc = subprocess.run(
                [self.docker, *args], cwd=cwd, capture_output=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Docker command timed out after {timeout}s.")
        return (proc.returncode,
                proc.stdout.decode("utf-8", "replace"),
                proc.stderr.decode("utf-8", "replace"))

    def check_dir(self, path):
        p = Path(path or "").expanduser()
        if not p.is_absolute() or not p.is_dir():
            raise ValueError(f"Local directory not found (absolute path required): {path!r}")
        return str(p.resolve())

    def join(self, directory, name):
        return str(Path(directory) / name)

    def exists(self, path):
        return Path(path).is_file()

    def write_text(self, path, text):
        Path(path).write_text(text, encoding="utf-8", newline="\n")

    def rename(self, src, dst):
        os.replace(src, dst)

    def remove(self, path):
        Path(path).unlink(missing_ok=True)


class _RemoteRunner:
    name = "remote"

    def __init__(self):
        profile = get_active_profile()
        self.prefix = profile.get("docker_command", "docker")
        if not _DOCKER_CMD_RE.fullmatch(self.prefix):
            raise ValueError("Invalid docker_command in host profile.")
        self.client = connect_active_host()
        self._sftp = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self._sftp:
            self._sftp.close()
        self.client.close()
        return False

    @property
    def sftp(self):
        if self._sftp is None:
            self._sftp = self.client.open_sftp()
        return self._sftp

    def run(self, args, cwd=None, timeout=_DEFAULT_TIMEOUT):
        command = self.prefix + " " + " ".join(shlex.quote(a) for a in args)
        if cwd:
            command = f"cd {shlex.quote(cwd)} && {command}"
        chan = self.client.get_transport().open_session()
        chan.exec_command(command)
        out, err = bytearray(), bytearray()
        deadline = time.monotonic() + timeout
        try:
            while True:
                got = False
                if chan.recv_ready():
                    data = chan.recv(65536)
                    out += data[: max(0, _MAX_CAPTURE - len(out))]
                    got = True
                if chan.recv_stderr_ready():
                    data = chan.recv_stderr(65536)
                    err += data[: max(0, _MAX_CAPTURE - len(err))]
                    got = True
                if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
                if not got:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Docker command timed out after {timeout}s.")
                    time.sleep(0.05)
            code = chan.recv_exit_status()
        finally:
            chan.close()
        return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def check_dir(self, path):
        path = (path or "").strip()
        if not path.startswith("/") or ".." in path.split("/") or "\x00" in path:
            raise ValueError(f"Remote directory must be an absolute path without '..': {path!r}")
        return posixpath.normpath(path)

    def join(self, directory, name):
        return posixpath.join(directory, name)

    def exists(self, path):
        try:
            self.sftp.stat(path)
            return True
        except IOError:
            return False

    def write_text(self, path, text):
        with self.sftp.open(path, "w") as f:
            f.write(text.encode("utf-8"))

    def rename(self, src, dst):
        self.sftp.posix_rename(src, dst)

    def remove(self, path):
        try:
            self.sftp.remove(path)
        except IOError:
            pass


def _runner(target):
    target = (target or "remote").strip().lower()
    if target == "local":
        return _LocalRunner()
    if target == "remote":
        return _RemoteRunner()
    raise ValueError("target must be 'remote' or 'local'.")


# ----------------------------------------------------- A. containers

@_safe
def list_containers(all_containers=True, name_filter="", target="remote"):
    args = ["ps"] + (["-a"] if all_containers else [])
    if name_filter:
        args += ["--filter", "name=" + _check(name_filter, _CONTAINER_RE, "name filter")]
    with _runner(target) as r:
        return _text(r.run(args), "No containers found.")


@_safe
def inspect_container(container, target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    with _runner(target) as r:
        code, out, err = r.run(["inspect", "--type", "container", container])
    if code != 0:
        return _text((code, out, err))
    c = _redact_env(json.loads(out)[0])
    cfg, st, hc, ns = (c.get(k) or {} for k in ("Config", "State", "HostConfig", "NetworkSettings"))
    health = (st.get("Health") or {}).get("Status", "n/a")
    ports = ns.get("Ports") or {}
    nets = {n: d.get("IPAddress", "") for n, d in (ns.get("Networks") or {}).items()}
    mounts = [f"{m.get('Source') or m.get('Name')} -> {m.get('Destination')} ({m.get('Mode') or 'rw'})"
              for m in c.get("Mounts") or []]
    lines = [
        f"Name: {c.get('Name', '').lstrip('/')}",
        f"ID: {c.get('Id', '')[:12]}",
        f"Image: {cfg.get('Image')}",
        f"Created: {c.get('Created')}",
        f"State: {st.get('Status')} (exit code {st.get('ExitCode')}, started {st.get('StartedAt')}, health {health})",
        f"Restart policy: {(hc.get('RestartPolicy') or {}).get('Name') or 'no'}",
        f"Entrypoint: {cfg.get('Entrypoint')}",
        f"Command: {cfg.get('Cmd')}",
        f"Working dir: {cfg.get('WorkingDir')}",
        f"User: {cfg.get('User') or 'default'}",
        f"Memory limit: {hc.get('Memory') or 'none'}",
        f"Ports: {json.dumps(ports)}",
        f"Networks: {json.dumps(nets)}",
        "Mounts: " + ("; ".join(mounts) or "none"),
        "Env: " + json.dumps(cfg.get("Env") or []),
        "Labels: " + json.dumps(cfg.get("Labels") or {}),
    ]
    return _clip("\n".join(lines))


@_safe
def start_container(container, target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    with _runner(target) as r:
        return _text(r.run(["start", container]), f"Started {container}.")


@_safe
def stop_container(container, timeout_seconds=10, target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    secs = _positive(timeout_seconds, "timeout_seconds", 3600)
    with _runner(target) as r:
        return _text(r.run(["stop", "-t", str(secs), container], timeout=secs + 60), f"Stopped {container}.")


@_safe
def restart_container(container, timeout_seconds=10, target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    secs = _positive(timeout_seconds, "timeout_seconds", 3600)
    with _runner(target) as r:
        return _text(r.run(["restart", "-t", str(secs), container], timeout=secs + 60), f"Restarted {container}.")


@_safe
def remove_container(container, force=False, remove_volumes=False, confirm=False, target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    if confirm is not True:
        return f"Refused: removing container '{container}' is destructive. Call again with confirm=True."
    args = ["rm"] + (["-f"] if force else []) + (["-v"] if remove_volumes else []) + [container]
    with _runner(target) as r:
        return _text(r.run(args), f"Removed {container}.")


@_safe
def get_container_stats(container="", target="remote"):
    args = ["stats", "--no-stream"]
    if container:
        args.append(_check(container, _CONTAINER_RE, "container"))
    with _runner(target) as r:
        return _text(r.run(args), "No running containers.")


# --------------------------------------------------------- B. images

@_safe
def list_images(name_filter="", target="remote"):
    args = ["images"]
    if name_filter:
        args.append(_check(name_filter, _IMAGE_RE, "image filter"))
    with _runner(target) as r:
        return _text(r.run(args), "No images found.")


@_safe
def inspect_image(image, target="remote"):
    image = _check(image, _IMAGE_RE, "image")
    with _runner(target) as r:
        return _text(r.run(["image", "inspect", image]))


@_safe
def pull_image(image, target="remote"):
    image = _check(image, _IMAGE_RE, "image")
    with _runner(target) as r:
        return _text(r.run(["pull", image], timeout=_LONG_TIMEOUT), f"Pulled {image}.", tail=True)


@_safe
def remove_image(image, force=False, confirm=False, target="remote"):
    image = _check(image, _IMAGE_RE, "image")
    if confirm is not True:
        return f"Refused: removing image '{image}' is destructive. Call again with confirm=True."
    args = ["rmi"] + (["-f"] if force else []) + [image]
    with _runner(target) as r:
        return _text(r.run(args), f"Removed {image}.")


@_safe
def build_image(context_path, tag, dockerfile="", no_cache=False, target="remote"):
    tag = _check(tag, _IMAGE_RE, "tag")
    with _runner(target) as r:
        context = r.check_dir(context_path)
        args = ["build", "-t", tag]
        if dockerfile:
            if "\x00" in dockerfile or "\n" in dockerfile:
                raise ValueError("Invalid dockerfile path.")
            args += ["-f", dockerfile]
        if no_cache:
            args.append("--no-cache")
        args.append(context)
        return _text(r.run(args, timeout=_LONG_TIMEOUT), f"Built {tag}.", tail=True)


@_safe
def tag_image(source_image, target_tag, target="remote"):
    source_image = _check(source_image, _IMAGE_RE, "source image")
    target_tag = _check(target_tag, _IMAGE_RE, "target tag")
    with _runner(target) as r:
        return _text(r.run(["tag", source_image, target_tag]), f"Tagged {source_image} as {target_tag}.")


# ------------------------------------------------------- C. debugging

@_safe
def get_logs(container, tail=100, since="", timestamps=False, target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    args = ["logs", "--tail", str(_positive(tail, "tail"))]
    if since:
        args += ["--since", _check(since, _SINCE_RE, "since value")]
    if timestamps:
        args.append("--timestamps")
    args.append(container)
    with _runner(target) as r:
        return _text(r.run(args), "No log output.", tail=True)


@_safe
def execute_command(container, command, user="", workdir="", timeout_seconds=60, target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    if not (command or "").strip() or "\x00" in command:
        raise ValueError("A non-empty command is required.")
    secs = _positive(timeout_seconds, "timeout_seconds", 3600)
    args = ["exec"]
    if user:
        args += ["-u", _check(user, re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}"), "user")]
    if workdir:
        if not workdir.startswith("/") or "\x00" in workdir:
            raise ValueError("workdir must be an absolute path inside the container.")
        args += ["-w", workdir]
    args += [container, "sh", "-c", command]
    with _runner(target) as r:
        code, out, err = r.run(args, timeout=secs)
    body = (out + ("\n[stderr]\n" + err if err.strip() else "")).strip()
    return f"Exit code: {code}\n{_clip(body) or '(no output)'}"


@_safe
def get_processes(container, ps_options="", target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    args = ["top", container]
    if ps_options:
        if not re.fullmatch(r"[A-Za-z0-9 -]{1,40}", ps_options):
            raise ValueError(f"Invalid ps options: {ps_options!r}")
        args += ps_options.split()
    with _runner(target) as r:
        return _text(r.run(args))


@_safe
def get_inspect(container, target="remote"):
    container = _check(container, _CONTAINER_RE, "container")
    with _runner(target) as r:
        code, out, err = r.run(["inspect", "--type", "container", container])
    if code != 0:
        return _text((code, out, err))
    return _clip(json.dumps(_redact_env(json.loads(out)[0]), indent=2))


@_safe
def get_networks(name="", target="remote"):
    args = ["network", "inspect", _check(name, _CONTAINER_RE, "network")] if name else ["network", "ls"]
    with _runner(target) as r:
        return _text(r.run(args))


@_safe
def get_volumes(name="", target="remote"):
    args = ["volume", "inspect", _check(name, _CONTAINER_RE, "volume")] if name else ["volume", "ls"]
    with _runner(target) as r:
        return _text(r.run(args))


# ---------------------------------------------------- D. Docker Compose

def _compose_args(r, project_dir, project_name):
    if not project_dir and not project_name:
        raise ValueError("Provide project_dir and/or project_name.")
    args = ["compose"]
    if project_name:
        args += ["-p", _check(project_name, _CONTAINER_RE, "project name")]
    cwd = r.check_dir(project_dir) if project_dir else None
    return args, cwd


@_safe
def list_compose_projects(target="remote"):
    with _runner(target) as r:
        return _text(r.run(["compose", "ls", "--all"]), "No Compose projects found.")


@_safe
def get_compose_status(project_dir="", project_name="", service="", target="remote"):
    with _runner(target) as r:
        args, cwd = _compose_args(r, project_dir, project_name)
        return _text(r.run(args + ["ps", "-a"] + _names(service), cwd=cwd), "No services found.")


@_safe
def start_compose_services(project_dir="", project_name="", services="", target="remote"):
    with _runner(target) as r:
        args, cwd = _compose_args(r, project_dir, project_name)
        return _text(r.run(args + ["up", "-d"] + _names(services), cwd=cwd, timeout=_LONG_TIMEOUT),
                     "Services started.", tail=True)


@_safe
def stop_compose_services(project_dir="", project_name="", services="", target="remote"):
    with _runner(target) as r:
        args, cwd = _compose_args(r, project_dir, project_name)
        return _text(r.run(args + ["stop"] + _names(services), cwd=cwd, timeout=300), "Services stopped.")


@_safe
def restart_compose_service(service, project_dir="", project_name="", target="remote"):
    names = _names(service)
    if len(names) != 1:
        raise ValueError("Provide exactly one service name.")
    with _runner(target) as r:
        args, cwd = _compose_args(r, project_dir, project_name)
        return _text(r.run(args + ["restart"] + names, cwd=cwd, timeout=300), f"Restarted {names[0]}.")


@_safe
def get_compose_logs(project_dir="", project_name="", service="", tail=100, since="", target="remote"):
    with _runner(target) as r:
        args, cwd = _compose_args(r, project_dir, project_name)
        args += ["logs", "--no-color", "--tail", str(_positive(tail, "tail"))]
        if since:
            args += ["--since", _check(since, _SINCE_RE, "since value")]
        return _text(r.run(args + _names(service), cwd=cwd), "No log output.", tail=True)


@_safe
def deploy_compose(project_dir, compose_content="", compose_file="", pull=True, target="remote"):
    """Optionally replace the compose file (validated, previous one kept as .bak),
    then pull images and run `up -d --remove-orphans`."""
    steps = []
    with _runner(target) as r:
        directory = r.check_dir(project_dir)
        custom = _check(compose_file, _COMPOSE_FILE_RE, "compose_file") if compose_file else ""
        file_args = ["-f", custom] if custom else []

        if (compose_content or "").strip():
            name = custom or next((n for n in _COMPOSE_DEFAULTS if r.exists(r.join(directory, n))),
                                  "compose.yaml")
            path = r.join(directory, name)
            staged_name = name + ".new"
            staged = r.join(directory, staged_name)
            r.write_text(staged, compose_content)

            validate = ["compose", "-f", staged_name]
            if not custom:
                override = next((n for n in _COMPOSE_OVERRIDES if r.exists(r.join(directory, n))), None)
                if override:
                    validate += ["-f", override]
            code, out, err = r.run(validate + ["config", "-q"], cwd=directory)
            if code != 0:
                r.remove(staged)
                return f"Invalid Compose configuration; nothing was deployed:\n{_clip((out + err).strip())}"

            if r.exists(path):
                backup = f"{path}.bak.{time.strftime('%Y%m%d%H%M%S')}"
                r.rename(path, backup)
                steps.append(f"Previous file saved as {backup}")
            r.rename(staged, path)
            steps.append(f"Installed {path}")
            file_args = ["-f", name] if custom else []
        else:
            code, out, err = r.run(["compose", *file_args, "config", "-q"], cwd=directory)
            if code != 0:
                return f"Invalid Compose configuration; nothing was deployed:\n{_clip((out + err).strip())}"

        if pull:
            code, out, err = r.run(["compose", *file_args, "pull"], cwd=directory, timeout=_LONG_TIMEOUT)
            if code != 0:
                return "\n".join(steps + [f"Image pull failed (exit {code}):", _clip((out + err).strip(), True)])
            steps.append("Images pulled")

        res = r.run(["compose", *file_args, "up", "-d", "--remove-orphans"], cwd=directory,
                    timeout=_LONG_TIMEOUT)
        steps.append(_text(res, "Services started.", tail=True))
        status = r.run(["compose", *file_args, "ps", "-a"], cwd=directory)
        steps.append(_text(status))
        return "\n".join(steps)
