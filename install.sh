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
die() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

say "Проверяю зависимости"
command -v rclone >/dev/null || die "нужен rclone 1.66+ — https://rclone.org/install/"
ver=$(rclone version | sed -n 's/^rclone v\([0-9]*\)\.\([0-9]*\).*/\1 \2/p')
set -- $ver
[ "${1:-0}" -gt 1 ] || [ "${2:-0}" -ge 66 ] || die "rclone $1.$2 слишком старый, нужен 1.66+ (https://rclone.org/install/)"
command -v fusermount3 >/dev/null || die "нужен fuse3 (apt install fuse3)"
python3 -c 'import PyQt6.QtWidgets, dbus, dbus.mainloop.pyqt6' 2>/dev/null \
  || die "нужны PyQt6 и dbus-python (apt install python3-pyqt6 python3-dbus python3-dbus.mainloop.pyqt6)"

say "Устанавливаю программу в $LIBDIR"
mkdir -p "$LIBDIR" "$BINDIR"
rm -rf "$LIBDIR/nimbus_drive"
cp -r "$SRC/nimbus_drive" "$LIBDIR/"
find "$LIBDIR/nimbus_drive" -name '__pycache__' -prune -exec rm -rf {} +
cat > "$BINDIR/nimbus-drive" <<EOF
#!/bin/sh
exec /usr/bin/env PYTHONPATH="$LIBDIR" python3 -m nimbus_drive "\$@"
EOF
chmod +x "$BINDIR/nimbus-drive"

say "Значки и ярлык"
mkdir -p "$DATADIR/icons/hicolor/scalable/apps" "$DATADIR/icons/hicolor/scalable/emblems" "$DATADIR/applications"
cp "$SRC"/data/icons/hicolor/scalable/apps/*.svg "$DATADIR/icons/hicolor/scalable/apps/"
cp "$SRC"/data/icons/hicolor/scalable/emblems/*.svg "$DATADIR/icons/hicolor/scalable/emblems/"
sed "s|@BINDIR@|$BINDIR|g" "$SRC/data/nimbus-drive.desktop" > "$DATADIR/applications/nimbus-drive.desktop"
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -qtf "$DATADIR/icons/hicolor" 2>/dev/null || true

say "Сервис systemd (пользовательский)"
mkdir -p "$UNITDIR"
sed "s|@BINDIR@|$BINDIR|g" "$SRC/data/nimbus-drive.service" > "$UNITDIR/nimbus-drive.service"
systemctl --user daemon-reload

if [ "${NO_DOLPHIN:-}" != 1 ] && command -v cmake >/dev/null && command -v dolphin >/dev/null; then
  say "Собираю плагин для Dolphin"
  cmake -S "$SRC/plugins/dolphin" -B "$SRC/build" -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=Release >/dev/null
  cmake --build "$SRC/build" -j"$(nproc)" >/dev/null
  say "Устанавливаю плагин Dolphin (нужен пароль администратора)"
  $SUDO cmake --install "$SRC/build" >/dev/null
elif [ "${NO_DOLPHIN:-}" != 1 ]; then
  echo "Плагин Dolphin пропущен: нужны cmake, g++, extra-cmake-modules, libkf6kio-dev, qt6-base-dev."
fi

say "Готово"
cat <<EOF
Запуск:
  systemctl --user enable --now nimbus-drive    # сервис (монтирует Google Drive)
  nimbus-drive tray                             # значок в трее и настройки
Первый запуск откроет окно «Аккаунт» — подключите Google Drive.
Значки в Dolphin появятся после перезапуска Dolphin.
EOF
