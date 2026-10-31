"""File states and inspection of rclone's VFS cache."""

import json
from pathlib import Path

# File states. The file manager plugins show them as emblems named "nimbus-<state>".
NONE = ""
CLOUD = "cloud"              # only in the cloud, takes no local space
DOWNLOADING = "downloading"  # being downloaded right now
CACHED = "cached"            # downloaded, opens instantly; may be evicted later
UPLOADING = "uploading"      # local changes not uploaded yet
OFFLINE = "offline"          # always kept locally (offline folder)
PENDING = "pending"          # offline copy changed, waiting for the next sync
SYNCING = "syncing"          # offline folder sync running
CONFLICT = "conflict"        # conflict copy created by sync
ERROR = "error"

LABELS = {
    CLOUD: "Online only",
    DOWNLOADING: "Downloading…",
    CACHED: "Available on this computer",
    UPLOADING: "Uploading…",
    OFFLINE: "Always available offline",
    PENDING: "Waiting to sync",
    SYNCING: "Syncing…",
    CONFLICT: "Conflict",
    ERROR: "Sync error",
}


class CacheIndex:
    """Reads rclone's VFS cache layout: data files plus JSON metadata per file."""

    def __init__(self, data_dir: Path, meta_dir: Path):
        self.data_dir = data_dir
        self.meta_dir = meta_dir

    def _meta(self, rel: str) -> dict | None:
        try:
            return json.loads((self.meta_dir / rel).read_text())
        except (OSError, ValueError):
            return None

    def state(self, rel: str) -> str:
        meta = self._meta(rel)
        if meta is None or not (self.data_dir / rel).is_file():
            return CLOUD
        if meta.get("Dirty"):
            return UPLOADING
        size = meta.get("Size", 0)
        if _covers(meta.get("Rs") or [], size):
            return CACHED
        # rclone saves the ranges a moment after a download ends; until then the
        # allocated size of the (sparse) data file tells a complete file apart.
        return CACHED if size and self.cached_bytes(rel) >= size else CLOUD

    def cached_bytes(self, rel: str) -> int:
        try:
            st = (self.data_dir / rel).stat()
        except OSError:
            return 0
        return st.st_blocks * 512

    def is_dir(self, rel: str) -> bool:
        return (self.meta_dir / rel).is_dir() or (self.data_dir / rel).is_dir()

    def is_dirty(self, rel: str) -> bool:
        meta = self._meta(rel)
        return bool(meta and meta.get("Dirty"))

    def evict(self, rel: str) -> int:
        """Remove one file from the cache. Caller must ensure it is closed and clean.

        rclone notices the missing data file on the next open and downloads it again.
        """
        freed = self.cached_bytes(rel)
        for base in (self.data_dir, self.meta_dir):
            try:
                (base / rel).unlink()
            except FileNotFoundError:
                pass
        return freed

    def iter_cached(self, rel_dir: str):
        root = self.data_dir / rel_dir if rel_dir else self.data_dir
        if root.is_file():
            yield rel_dir
            return
        for p in root.rglob("*"):
            if p.is_file():
                yield str(p.relative_to(self.data_dir))


def _covers(ranges: list, size: int) -> bool:
    """True if the cached byte ranges cover the whole file."""
    if size == 0:
        return True
    pos = 0
    for r in sorted(ranges, key=lambda r: r.get("Pos", 0)):
        start, length = r.get("Pos", 0), r.get("Size", 0)
        if start > pos:
            return False
        pos = max(pos, start + length)
        if pos >= size:
            return True
    return pos >= size
