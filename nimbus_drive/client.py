"""D-Bus client for the daemon, used by the tray, the settings window and the CLI."""

import json

import dbus

from . import DBUS_IFACE, DBUS_NAME, DBUS_PATH


class DaemonClient:
    def __init__(self, bus=None):
        self.bus = bus or dbus.SessionBus()

    @property
    def iface(self):
        obj = self.bus.get_object(DBUS_NAME, DBUS_PATH, introspect=False)
        return dbus.Interface(obj, DBUS_IFACE)

    def running(self) -> bool:
        return bool(self.bus.name_has_owner(DBUS_NAME))

    def summary(self) -> dict:
        return json.loads(str(self.iface.GetSummary()))

    def status(self, path: str) -> str:
        return str(self.iface.GetStatus(path))

    def download(self, paths: list[str]) -> str:
        return str(self.iface.Download(paths))

    def free_space(self, paths: list[str]) -> str:
        return str(self.iface.FreeSpace(paths))

    def set_offline(self, paths: list[str], enabled: bool, remove_local: bool = False) -> str:
        return str(self.iface.SetOffline(paths, enabled, remove_local, timeout=120))

    def sync_now(self) -> None:
        self.iface.SyncNow()

    def force_sync(self, folder: str) -> None:
        self.iface.ForceSync(folder)

    def set_paused(self, paused: bool) -> None:
        self.iface.SetPaused(paused)

    def reload(self) -> None:
        self.iface.Reload()

    def on_summary(self, callback) -> None:
        self.bus.add_signal_receiver(lambda s: callback(json.loads(str(s))),
                                     signal_name="SummaryChanged", dbus_interface=DBUS_IFACE,
                                     bus_name=DBUS_NAME, path=DBUS_PATH)
