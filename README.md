# Nimbus Drive

Google Drive for Linux that behaves like Google Drive for desktop on Windows — built on [rclone](https://rclone.org).

- **Files on demand.** Your whole Drive appears in a folder (`~/GoogleDrive`). Nothing takes disk space until you open it; opening a file downloads it.
- **You can see what is local.** Dolphin shows an emblem on every file:

  | Emblem | Meaning |
  |---|---|
  | ![](data/icons/hicolor/scalable/emblems/nimbusdrive-cloud.svg) | Online only — downloads when you open it |
  | ![](data/icons/hicolor/scalable/emblems/nimbusdrive-downloading.svg) | Downloading right now |
  | ![](data/icons/hicolor/scalable/emblems/nimbusdrive-cached.svg) | Downloaded, opens instantly |
  | ![](data/icons/hicolor/scalable/emblems/nimbusdrive-uploading.svg) | Your changes are being uploaded |
  | ![](data/icons/hicolor/scalable/emblems/nimbusdrive-offline.svg) | Always available offline |
  | ![](data/icons/hicolor/scalable/emblems/nimbusdrive-pending.svg) | Changed offline, waiting for the next sync |
  | ![](data/icons/hicolor/scalable/emblems/nimbusdrive-conflict.svg) | Conflict copy — both versions were kept |

- **Right-click menu** in Dolphin: *Download*, *Free up space*, *Always keep offline*, *Sync now*.
- **Offline folders.** Tick folders in a tree and they are kept as real local copies in `~/GoogleDrive Offline`, synced both ways with `rclone bisync`. Conflicts keep both versions (`report.conflict1.docx`).
- **Tray icon** with progress, errors and a settings window. Notifications for conflicts and errors.
- Native Google Docs/Sheets/Slides appear as small `.link.html` files that open in the browser.

## Install

Requirements: rclone **1.66 or newer** (distribution packages are often older — get it from [rclone.org/install](https://rclone.org/install/)), fuse3, Python 3 with PyQt6 and dbus-python. For the Dolphin emblems and menu: KDE Plasma 6 and build tools.

Debian/Ubuntu:

```bash
git clone https://github.com/mmukhanov/nimbus-drive.git && cd nimbus-drive
sudo apt install fuse3 python3-pyqt6 python3-dbus python3-dbus.mainloop.pyqt6 \
  cmake g++ extra-cmake-modules libkf6kio-dev qt6-base-dev
./install.sh
systemctl --user enable --now nimbus-drive
nimbus-drive tray
```

The window opens on the *Account* tab the first time. Restart Dolphin to see the emblems.

`./install.sh` puts the program in `~/.local`; only the Dolphin plugin goes into the system Qt plugin directory (it asks for your password once). `NO_DOLPHIN=1 ./install.sh` skips it. `./uninstall.sh` removes everything except your files and settings.

## Your own Google client ID (needed in 2026)

rclone's shared Google client ID is being retired by Google during 2026. Create your own — free, about five minutes — following [rclone's guide](https://rclone.org/drive/#making-your-own-client-id), then use *Account → Reconnect with your own client_id*. Keep the app in "Testing" mode and add yourself as a test user; you do not need Google's verification for personal use.

## How it works

```
Dolphin ── emblems / menu (C++ KIO plugins)
   │ D-Bus  io.github.nimbusdrive
nimbus-drive daemon (Python, systemd user service)
   ├── rclone mount  --vfs-cache-mode full   → ~/GoogleDrive   (files on demand)
   │      └── rc API on a private unix socket   (live transfers, upload queue)
   └── rclone bisync per offline folder        → ~/GoogleDrive Offline
nimbus-drive tray (PyQt6): tray icon, settings, folder picker
```

File states come from rclone's VFS cache metadata and its live transfer list, never from listing Drive, so emblems stay instant even on large drives. "Free up space" removes a file from the cache only when it is closed and fully uploaded.

Safety: the rc socket lives in a `0700` runtime directory; tokens stay in rclone's own config; the first sync of an offline folder only merges (never deletes); bisync stops if more than half of the files would be deleted and asks you to confirm; removing an offline folder moves the local copy to the Trash, never deletes it.

## Command line

```
nimbus-drive status               # what is happening
nimbus-drive download <paths>     # make files available on this computer
nimbus-drive free <paths>         # online only again
nimbus-drive offline <folders>    # always keep offline (two-way sync)
nimbus-drive online <folders> [--trash-local]
nimbus-drive sync                 # sync offline folders now
```

## Limits

- One Google account per installation (pick another rclone remote in *Account* to switch).
- Emblems and the context menu are for Dolphin; other file managers get the folder, tray and CLI.
- Very deep offline folders can hit rclone bisync's file name limit; the app tells you when that happens.

## License

MIT
