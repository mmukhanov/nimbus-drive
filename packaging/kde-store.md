# KDE Store listing

Category: **Dolphin Service Menus** (or *Applications → Network*).
Link the GitHub release; do not upload a copy of the code.

## Name

Nimbus Drive — unofficial Google Drive client

## Summary

Google Drive in Dolphin like on Windows: files on demand with status emblems, offline folders, tray icon.

## Description

Nimbus Drive puts your whole Google Drive™ in a folder and shows on every file in Dolphin whether it is only in the cloud, downloading, downloaded or always kept offline. Nothing takes disk space until you open it.

- Files on demand through rclone's VFS cache
- Dolphin emblems: online only, downloading, downloaded, uploading, offline, conflict
- Right-click: Download, Free up space, Always keep offline, Sync now
- Offline folders with two-way sync (rclone bisync); conflicts keep both versions
- Tray icon that follows the light/dark theme, notifications for conflicts and errors

Beta. Needs rclone 1.66+ and your own Google OAuth client ID (free; the README explains how). Not affiliated with Google. Google Drive is a trademark of Google LLC.

Source and install: https://github.com/mmukhanov/nimbus-drive

## Screenshots to attach

1. Dolphin with cloud / downloaded / offline emblems
2. The right-click Google Drive submenu
3. Settings window, Offline folders tab with the folder tree
4. Tray icon with its tooltip
