#!/bin/sh
# Installs Nimbus Drive for the current user. The Dolphin plugins go into the system Qt
# plugin directory, which needs root once (sudo, or SUDO=pkexec ./install.sh).
set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
PREFIX=${PREFIX:-$HOME/.local}
BINDIR=$PREFIX/bin
LIBDIR=$PREFIX/share/nimbus-drive
DATADIR=${XDG_DATA_HOME:-$HOME/.local/share}
UNITDIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
SUDO=${SUDO:-sudo}

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

say "Checking dependencies"
command -v rclone >/dev/null || die "rclone 1.66+ is required — https://rclone.org/install/"
ver=$(rclone version | sed -n 's/^rclone v\([0-9]*\)\.\([0-9]*\).*/\1 \2/p')
set -- $ver
[ "${1:-0}" -gt 1 ] || [ "${2:-0}" -ge 66 ] || die "rclone $1.$2 is too old, 1.66+ is required (https://rclone.org/install/)"
command -v fusermount3 >/dev/null || die "fuse3 is required (apt install fuse3)"
python3 -c 'import PyQt6.QtWidgets, dbus, dbus.mainloop.pyqt6' 2>/dev/null \
  || die "PyQt6 and dbus-python are required (apt install python3-pyqt6 python3-dbus python3-dbus.mainloop.pyqt6)"

say "Installing the app to $LIBDIR"
mkdir -p "$LIBDIR" "$BINDIR"
rm -rf "$LIBDIR/nimbus_drive"
cp -r "$SRC/nimbus_drive" "$LIBDIR/"
find "$LIBDIR/nimbus_drive" -name '__pycache__' -prune -exec rm -rf {} +
cat > "$BINDIR/nimbus-drive" <<EOF
#!/bin/sh
exec /usr/bin/env PYTHONPATH="$LIBDIR" python3 -m nimbus_drive "\$@"
EOF
chmod +x "$BINDIR/nimbus-drive"

say "Icons and launcher"
for sub in apps emblems status; do
  mkdir -p "$DATADIR/icons/hicolor/scalable/$sub"
  cp "$SRC"/data/icons/hicolor/scalable/$sub/*.svg "$DATADIR/icons/hicolor/scalable/$sub/"
done
mkdir -p "$DATADIR/applications"
rm -f "$DATADIR/applications/nimbus-drive.desktop"  # name used by 0.1.0 before the rename
sed "s|@BINDIR@|$BINDIR|g" "$SRC/data/io.github.nimbusdrive.desktop" > "$DATADIR/applications/io.github.nimbusdrive.desktop"
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -qtf "$DATADIR/icons/hicolor" 2>/dev/null || true

say "systemd user service"
mkdir -p "$UNITDIR"
sed "s|@BINDIR@|$BINDIR|g" "$SRC/data/nimbus-drive.service" > "$UNITDIR/nimbus-drive.service"
systemctl --user daemon-reload

if [ "${NO_DOLPHIN:-}" != 1 ] && command -v cmake >/dev/null && command -v dolphin >/dev/null; then
  say "Building the Dolphin plugin"
  cmake -S "$SRC/plugins/dolphin" -B "$SRC/build" -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=Release >/dev/null
  cmake --build "$SRC/build" -j"$(nproc)" >/dev/null
  say "Installing the Dolphin plugin (needs your admin password)"
  $SUDO cmake --install "$SRC/build" >/dev/null
elif [ "${NO_DOLPHIN:-}" != 1 ]; then
  echo "Dolphin plugin skipped: needs cmake, g++, extra-cmake-modules, libkf6kio-dev, qt6-base-dev."
fi

say "Done"
cat <<EOF
Start:
  systemctl --user enable --now nimbus-drive    # the service (mounts Google Drive)
  nimbus-drive tray                             # tray icon and settings
The first start opens the Account tab — connect your Google Drive there.
Restart Dolphin to see the file emblems.
EOF
