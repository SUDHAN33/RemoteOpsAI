
import os
import posixpath

from pathlib import Path, PurePosixPath

from .ssh_manager import create_ssh_client

from config import (
    REMOTE_BASE_DIR,
    UPLOAD_DIR,
    DOWNLOAD_DIR
)

MAX_READ_SIZE = 1024 * 1024       # 1 MB
MAX_TRANSFER_SIZE = 100 * 1024 * 1024  # 100 MB


def get_safe_remote_path(relative_path: str) -> str:
    """
    Resolve a relative path inside the configured remote base directory.
    Reject absolute paths and parent-directory traversal.
    """

    if not relative_path or "\x00" in relative_path:
        raise ValueError("Invalid remote path")

    if "\\" in relative_path:
        raise ValueError("Use Linux-style forward slashes")

    relative = PurePosixPath(relative_path)

    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Path must stay inside the remote base directory")

    base = posixpath.normpath(REMOTE_BASE_DIR)
    target = posixpath.normpath(posixpath.join(base, relative_path))

    if posixpath.commonpath([base, target]) != base:
        raise ValueError("Access outside the remote base directory is denied")

    return target


def list_remote_files(relative_path="."):
    """
    List files and directories in a remote directory.
    """

    remote_path = get_safe_remote_path(relative_path)

    client = create_ssh_client()

    try:
        sftp = client.open_sftp()

        try:
            entries = sftp.listdir_attr(remote_path)

            results = []

            for entry in entries:
                file_type = (
                    "DIR" if entry.st_mode & 0o170000 == 0o040000
                    else "FILE"
                )

                results.append({
                    "name": entry.filename,
                    "type": file_type,
                    "size": entry.st_size
                })

            return results

        finally:
            sftp.close()

    finally:
        client.close()


def read_remote_file(relative_path):
    """
    Read a remote text file, limited to 1 MB.
    """

    remote_path = get_safe_remote_path(relative_path)

    client = create_ssh_client()

    try:
        sftp = client.open_sftp()

        try:
            attributes = sftp.stat(remote_path)

            if attributes.st_size > MAX_READ_SIZE:
                raise ValueError("File exceeds the 1 MB reading limit")

            with sftp.open(remote_path, "rb") as remote_file:
                content = remote_file.read(MAX_READ_SIZE + 1)

            if len(content) > MAX_READ_SIZE:
                raise ValueError("File exceeds the reading limit")

            return content.decode("utf-8", errors="replace")

        finally:
            sftp.close()

    finally:
        client.close()


def upload_local_file(filename, remote_relative_path):
    """
    Upload a file from the local uploads directory.
    Existing remote files are not overwritten.
    """

    if Path(filename).name != filename or filename in ("", ".", ".."):
        raise ValueError("Provide only a filename from the uploads directory")

    local_file = UPLOAD_DIR / filename

    if not local_file.is_file():
        raise FileNotFoundError("File not found in uploads directory")

    if local_file.stat().st_size > MAX_TRANSFER_SIZE:
        raise ValueError("Upload exceeds the 100 MB limit")

    remote_path = get_safe_remote_path(remote_relative_path)

    client = create_ssh_client()

    try:
        sftp = client.open_sftp()

        try:
            # Check whether the destination already exists
            try:
                sftp.stat(remote_path)
                raise FileExistsError(
                    "Remote destination exists. Choose another filename."
                )
            except FileNotFoundError:
                pass
            except OSError as error:
                # Paramiko may report missing paths as IOError/OSError.
                if getattr(error, "errno", None) not in (2,):
                    raise

            sftp.put(str(local_file), remote_path, confirm=True)

            return f"Successfully uploaded {filename}"

        finally:
            sftp.close()

    finally:
        client.close()


def download_remote_file(relative_path):
    """
    Download a remote file into the local downloads directory.
    """

    remote_path = get_safe_remote_path(relative_path)

    filename = PurePosixPath(relative_path).name

    if filename in ("", ".", ".."):
        raise ValueError("Invalid filename")

    local_file = DOWNLOAD_DIR / filename

    if local_file.exists():
        raise FileExistsError(
            "Local download already exists. Rename or move it first."
        )

    client = create_ssh_client()

    try:
        sftp = client.open_sftp()

        try:
            attributes = sftp.stat(remote_path)

            if attributes.st_size > MAX_TRANSFER_SIZE:
                raise ValueError("Download exceeds the 100 MB limit")

            if not (attributes.st_mode & 0o170000 == 0o100000):
                raise ValueError("Only regular files can be downloaded")

            sftp.get(remote_path, str(local_file))

            return f"Downloaded successfully: {local_file}"

        finally:
            sftp.close()

    finally:
        client.close()


def create_remote_directory(relative_path):
    """
    Create a directory under the configured remote base directory.
    """

    remote_path = get_safe_remote_path(relative_path)

    client = create_ssh_client()

    try:
        sftp = client.open_sftp()

        try:
            sftp.mkdir(remote_path)
            return f"Directory created: {remote_path}"

        finally:
            sftp.close()

    finally:
        client.close()
