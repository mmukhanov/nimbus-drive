# Changelog

## 0.1.0 — 2026-10-31

First public beta.

- Files on demand: the whole Drive mounted in `~/GoogleDrive` with rclone's VFS cache.
- Dolphin emblems for online-only, downloading, downloaded, uploading, offline, pending and conflict.
- Dolphin context menu: download, free up space, always keep offline, sync now.
- Offline folders kept as local copies with two-way `rclone bisync`, chosen in a folder tree.
- Tray icon (black/white, follows the light or dark theme) with status, progress and notifications.
- Account setup with your own Google OAuth client ID.
- Command line: `status`, `download`, `free`, `offline`, `online`, `sync`.
