
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Remote server connection
REMOTE_HOST = os.getenv("REMOTE_HOST")
REMOTE_PORT = int(os.getenv("REMOTE_PORT", "22"))
REMOTE_USERNAME = os.getenv("REMOTE_USERNAME")
REMOTE_BASE_DIR = os.getenv("REMOTE_BASE_DIR")

# Local project directories
PROJECT_DIR = Path(__file__).resolve().parent

UPLOAD_DIR = PROJECT_DIR / "uploads"
DOWNLOAD_DIR = PROJECT_DIR / "downloads"

# Create folders if they don't exist
UPLOAD_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Validate configuration
required_settings = [
    REMOTE_HOST,
    REMOTE_USERNAME,
    REMOTE_BASE_DIR
]

if not all(required_settings):
    raise RuntimeError("Missing remote server configuration")


if not REMOTE_BASE_DIR.startswith("/"):
    raise RuntimeError("REMOTE_BASE_DIR must be an absolute Linux path")
