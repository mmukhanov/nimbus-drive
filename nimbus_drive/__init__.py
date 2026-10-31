"""Nimbus Drive: a Google Drive desktop client for Linux built on rclone."""

__version__ = "0.1.0"
HOMEPAGE = "https://github.com/mmukhanov/nimbus-drive"

APP_ID = "nimbus-drive"
DBUS_NAME = "io.github.nimbusdrive"
DBUS_PATH = "/io/github/nimbusdrive"
DBUS_IFACE = "io.github.nimbusdrive.Daemon"

# Minimum rclone version: bisync --resilient/--recover/--conflict-resolve need 1.66+.
MIN_RCLONE = (1, 66)
