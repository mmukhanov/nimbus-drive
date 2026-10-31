#!/bin/sh
# Removes Nimbus Drive. Your files in Google Drive and your offline copies are not touched;
# the rclone remote (account) stays in rclone's own config.
set -eu

PREFIX=${PREFIX:-$HOME/.local}
DATADIR=${XDG_DATA_HOME:-$HOME/.local/share}
CONFDIR=${XDG_CONFIG_HOME:-$HOME/.config}
SUDO=${SUDO:-sudo}

systemctl --user disable --now nimbus-drive.service 2>/dev/null || true
pkill -f 'nimbus_drive tray' 2>/dev/null || true

rm -f "$CONFDIR/systemd/user/nimbus-drive.service" "$CONFDIR/autostart/nimbus-drive-tray.desktop"
systemctl --user daemon-reload
rm -f "$PREFIX/bin/nimbus-drive" "$DATADIR/applications/io.github.nimbusdrive.desktop" "$DATADIR/applications/nimbus-drive.desktop"
rm -f "$DATADIR"/icons/hicolor/scalable/apps/io.github.nimbusdrive.svg
rm -f "$DATADIR"/icons/hicolor/scalable/emblems/nimbusdrive-*.svg "$DATADIR"/icons/hicolor/scalable/status/nimbusdrive-*.svg
rm -rf "$PREFIX/share/nimbus-drive"

PLUGINDIR=$(qtpaths6 --plugin-dir 2>/dev/null || qmake6 -query QT_INSTALL_PLUGINS 2>/dev/null || true)
if [ -n "$PLUGINDIR" ] && { [ -e "$PLUGINDIR/kf6/overlayicon/nimbusoverlay.so" ] || [ -e "$PLUGINDIR/kf6/kfileitemaction/nimbusactions.so" ]; }; then
  echo "Removing the Dolphin plugin (needs your admin password)"
  $SUDO rm -f "$PLUGINDIR/kf6/overlayicon/nimbusoverlay.so" "$PLUGINDIR/kf6/kfileitemaction/nimbusactions.so" \
    || echo "Could not remove the Dolphin plugin; remove these files as root: $PLUGINDIR/kf6/overlayicon/nimbusoverlay.so $PLUGINDIR/kf6/kfileitemaction/nimbusactions.so"
fi
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -qtf "$DATADIR/icons/hicolor" 2>/dev/null || true

echo "Nimbus Drive removed. Settings remain in $CONFDIR/nimbus-drive, state in ${XDG_STATE_HOME:-$HOME/.local/state}/nimbus-drive, the cache in ${XDG_CACHE_HOME:-$HOME/.cache}/nimbus-drive."
