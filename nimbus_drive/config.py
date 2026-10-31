"""User configuration and XDG locations."""

import json
import os
import tempfile
from pathlib import Path

from . import APP_ID


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / APP_ID
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / APP_ID
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / APP_ID
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / APP_ID

CONFIG_FILE = CONFIG_DIR / "config.json"
RC_SOCKET = RUNTIME_DIR / "rc.sock"
BISYNC_WORKDIR = STATE_DIR / "bisync"
MIRROR_STATE_FILE = STATE_DIR / "mirror.json"
LOG_FILE = STATE_DIR / "rclone.log"

DEFAULTS = {
    # rclone remote name without the colon, e.g. "gdrive". Empty = not configured yet.
    "remote": "",
    # Where the whole Drive appears, files downloaded on demand.
    "mount_point": "~/GoogleDrive",
    # Where folders marked "available offline" are kept as real local copies.
    "mirror_root": "~/GoogleDrive Offline",
    # Remote-relative folder paths kept offline with two-way sync.
    "offline_folders": [],
    "cache_max_size": "10G",
    "cache_max_age": "720h",
    "sync_interval_minutes": 5,
    # How native Google Docs/Sheets/Slides appear in the mount.
    "export_formats": "link.html",
    "mount_extra_args": [],
    "notifications": True,
}


class Config(dict):
    """Config dict with defaults filled in and helpers for paths."""

    @classmethod
    def load(cls) -> "Config":
        data = dict(DEFAULTS)
        try:
            data.update(json.loads(CONFIG_FILE.read_text()))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Не удалось прочитать {CONFIG_FILE}: {e}") from e
        return cls(data)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Atomic write so a crash never leaves a half-written config.
        fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config.", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(dict(self), f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, CONFIG_FILE)

    @property
    def mount_path(self) -> Path:
        return Path(os.path.expanduser(self["mount_point"])).absolute()

    @property
    def mirror_path(self) -> Path:
        return Path(os.path.expanduser(self["mirror_root"])).absolute()

    @property
    def configured(self) -> bool:
        return bool(self["remote"])

    def offline_folders(self) -> list[str]:
        return [normalize_rel(p) for p in self["offline_folders"] if normalize_rel(p)]


def normalize_rel(path: str) -> str:
    """Normalize a remote-relative path: no leading/trailing slashes, no '.' parts."""
    parts = [p for p in str(path).split("/") if p not in ("", ".")]
    if ".." in parts:
        raise ValueError(f"недопустимый путь: {path}")
    return "/".join(parts)


def is_under(rel: str, folder: str) -> bool:
    return rel == folder or rel.startswith(folder + "/")


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
