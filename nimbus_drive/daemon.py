"""Background service: runs the rclone mount, tracks file states, serves the D-Bus API."""

import errno
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.pyqt6 import DBusQtMainLoop
from PyQt6.QtCore import QCoreApplication, QObject, QProcess, QTimer

from . import DBUS_IFACE, DBUS_NAME, DBUS_PATH, MIN_RCLONE, __version__
from . import config as C
from . import status as S
from .mirror import MirrorManager
from .rc import RcClient, RcError


def rclone_version() -> tuple[int, int]:
    out = subprocess.run(["rclone", "version"], capture_output=True, text=True).stdout
    m = re.search(r"rclone v(\d+)\.(\d+)", out)
    return (int(m[1]), int(m[2])) if m else (0, 0)


def human_size(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024


class Mount(QObject):
    """Owns the `rclone mount` process and restarts it if it dies."""

    def __init__(self, daemon: "Daemon"):
        super().__init__()
        self.d = daemon
        self.proc: QProcess | None = None
        self.ready = False
        self.error = ""
        self.restarts = 0
        self.stopping = False

    def start(self) -> None:
        cfg = self.d.cfg
        if not cfg.configured or self.proc is not None:
            return
        mp = cfg.mount_path
        self._cleanup_stale(mp)
        if os.path.ismount(mp):
            self.error = f"{mp} уже смонтирована другой программой — отключите её."
            self.d.notify("Google Drive не подключён", self.error)
            return
        try:
            mp.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.error = f"Не удалось создать {mp}: {e}"
            return
        if any(mp.iterdir()):
            self.error = f"Папка {mp} не пуста — выберите пустую папку для Google Drive."
            self.d.notify("Google Drive не подключён", self.error)
            return
        if len(str(C.RC_SOCKET).encode()) >= 104:  # sun_path limit
            self.error = f"Слишком длинный путь к сокету: {C.RC_SOCKET}"
            return
        C.ensure_private_dir(C.RUNTIME_DIR)
        C.STATE_DIR.mkdir(parents=True, exist_ok=True)
        if C.RC_SOCKET.is_socket():
            C.RC_SOCKET.unlink()

        args = [
            "mount", f"{cfg['remote']}:", str(mp),
            "--vfs-cache-mode", "full",
            "--cache-dir", str(C.CACHE_DIR / "rclone"),
            "--vfs-cache-max-size", cfg["cache_max_size"],
            "--vfs-cache-max-age", cfg["cache_max_age"],
            "--dir-cache-time", "1000h", "--poll-interval", "1m",
            "--drive-export-formats", cfg["export_formats"],
            "--volname", "Google Drive",
            # The socket lives in a 0700 directory, so only this user can reach it.
            "--rc", "--rc-addr", f"unix://{C.RC_SOCKET}", "--rc-no-auth",
            "--log-file", str(C.LOG_FILE), "--log-level", "NOTICE",
            *cfg["mount_extra_args"],
        ]
        self.error = ""
        self.stopping = False
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.finished.connect(self._finished)
        self.proc.start("rclone", args)
        self._wait_ready(time.time())

    def _wait_ready(self, since: float) -> None:
        if self.proc is None:
            return
        try:
            if C.RC_SOCKET.is_socket():
                st = self.d.rc.call("vfs/stats", timeout=5, fs=f"{self.d.cfg['remote']}:")
                disk = st["diskCache"]
                self.d.cache = S.CacheIndex(Path(disk["path"]), Path(disk["pathMeta"]))
                self.ready = True
                self.restarts = 0
                self.d.changed([str(self.d.cfg.mount_path) + "/"])
                self.d.summary_changed()
                return
        except (RcError, KeyError):
            pass
        if time.time() - since > 120:
            self.error = "rclone не ответил за 2 минуты"
            self.stop()
            return
        QTimer.singleShot(300, lambda: self._wait_ready(since))

    def _finished(self, code: int, _status) -> None:
        out = bytes(self.proc.readAll()).decode(errors="replace").strip()
        self.proc.deleteLater()
        self.proc = None
        was_ready, self.ready = self.ready, False
        self.d.summary_changed()
        if self.stopping:
            return
        # rclone logs to a file; its last error there says more than the exit code.
        try:
            log = C.LOG_FILE.read_text(errors="replace").splitlines()[-50:]
        except OSError:
            log = []
        errors = [l.split(":", 3)[-1].strip() for l in log if "ERROR" in l or "CRITICAL" in l]
        self.error = (errors or out.splitlines() or [f"rclone завершился с кодом {code}"])[-1][:300]
        self.restarts += 1
        delay = min(300, 5 * 2 ** min(self.restarts, 6))
        if was_ready or self.restarts == 1:
            self.d.notify("Google Drive отключился", f"{self.error}\nПереподключусь через {delay} с.")
        QTimer.singleShot(delay * 1000, self.start)

    def stop(self) -> None:
        self.stopping = True
        self.ready = False
        if self.proc is not None:
            self.proc.terminate()
            if not self.proc.waitForFinished(15000):
                self.proc.kill()
                self.proc.waitForFinished(3000)
            self._cleanup_stale(self.d.cfg.mount_path)

    @staticmethod
    def _cleanup_stale(mp: Path) -> None:
        """Detach a FUSE mount left behind by a crashed rclone (stat fails with ENOTCONN)."""
        try:
            os.stat(mp)
        except OSError as e:
            if e.errno == errno.ENOTCONN:
                subprocess.run(["fusermount3", "-uz", str(mp)], capture_output=True)


class DBusService(dbus.service.Object):
    def __init__(self, bus, daemon: "Daemon"):
        super().__init__(bus, DBUS_PATH)
        self.d = daemon

    @dbus.service.method(DBUS_IFACE, out_signature="as")
    def GetRoots(self):
        return [str(self.d.cfg.mount_path), str(self.d.cfg.mirror_path)]

    @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="s")
    def GetStatus(self, path):
        return self.d.status(str(path))

    @dbus.service.method(DBUS_IFACE, in_signature="as", out_signature="as")
    def GetStatuses(self, paths):
        return [self.d.status(str(p)) for p in paths]

    @dbus.service.method(DBUS_IFACE, out_signature="s")
    def GetSummary(self):
        return json.dumps(self.d.summary(), ensure_ascii=False)

    @dbus.service.method(DBUS_IFACE, in_signature="as", out_signature="s")
    def Download(self, paths):
        return self.d.download([Path(p) for p in paths])

    @dbus.service.method(DBUS_IFACE, in_signature="as", out_signature="s")
    def FreeSpace(self, paths):
        return self.d.free_space([Path(p) for p in paths])

    @dbus.service.method(DBUS_IFACE, in_signature="asbb", out_signature="s")
    def SetOffline(self, paths, enabled, remove_local):
        return self.d.set_offline([Path(p) for p in paths], bool(enabled), bool(remove_local))

    @dbus.service.method(DBUS_IFACE)
    def SyncNow(self):
        self.d.mirror.paused = False
        self.d.mirror.sync_all()

    @dbus.service.method(DBUS_IFACE, in_signature="s")
    def ForceSync(self, folder):
        self.d.mirror.sync(folder, force=True)

    @dbus.service.method(DBUS_IFACE, in_signature="b")
    def SetPaused(self, paused):
        self.d.mirror.paused = bool(paused)
        self.d.summary_changed()

    @dbus.service.method(DBUS_IFACE)
    def Reload(self):
        QTimer.singleShot(0, self.d.reload)

    @dbus.service.method(DBUS_IFACE, out_signature="s")
    def Version(self):
        return __version__

    @dbus.service.signal(DBUS_IFACE, signature="as")
    def StatusChanged(self, paths):
        pass

    @dbus.service.signal(DBUS_IFACE, signature="s")
    def SummaryChanged(self, summary):
        pass


class Daemon(QObject):
    def __init__(self):
        super().__init__()
        self.cfg = C.Config.load()
        self.rc = RcClient(C.RC_SOCKET, timeout=3)
        self.cache: S.CacheIndex | None = None
        self.downloads: dict[str, dict] = {}   # rel -> {"pct", "size", "bytes"}
        self.uploads: dict[str, dict] = {}
        self.requested: dict[str, float] = {}  # rel -> time, downloads we started
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="download")
        self.bus = dbus.SessionBus()
        self.service = DBusService(self.bus, self)
        self.mount = Mount(self)
        self.mirror = MirrorManager(self.cfg)
        self.mirror.changed.connect(self.changed)
        self.mirror.summaryChanged.connect(self.summary_changed)
        self.mirror.notify.connect(self.notify)
        self._summary_pending = False

        self.poller = QTimer(self)
        self.poller.timeout.connect(self.poll)
        self.poller.start(1000)

    def start(self) -> None:
        self.mount.start()
        QTimer.singleShot(15_000, self.mirror.sync_all)

    def shutdown(self) -> None:
        self.poller.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self.mirror.proc is not None:
            self.mirror.proc.terminate()
            self.mirror.proc.waitForFinished(10000)
        self.mount.stop()

    def reload(self) -> None:
        old = self.cfg
        self.cfg = C.Config.load()
        if old.mirror_path != self.cfg.mirror_path:
            # New location: every offline folder starts over with a merge-only resync.
            self.mirror.reset_all()
        self.mirror.apply_config(self.cfg)
        keys = ("remote", "mount_point", "cache_max_size", "cache_max_age",
                "export_formats", "mount_extra_args")
        if any(old[k] != self.cfg[k] for k in keys):
            self.mount.stop()
            self.cache = None
            QTimer.singleShot(500, self.mount.start)
        self.mirror.sync_all()
        self.changed([str(self.cfg.mount_path) + "/", str(self.cfg.mirror_path) + "/"])
        self.summary_changed()

    # ---- signals out ----

    def changed(self, paths: list[str]) -> None:
        if paths:
            self.service.StatusChanged(paths)

    def summary_changed(self) -> None:
        # Coalesce bursts of changes into one signal.
        if not self._summary_pending:
            self._summary_pending = True
            QTimer.singleShot(200, self._emit_summary)

    def _emit_summary(self) -> None:
        self._summary_pending = False
        self.service.SummaryChanged(json.dumps(self.summary(), ensure_ascii=False))

    def notify(self, title: str, body: str) -> None:
        if not self.cfg["notifications"]:
            return
        try:
            obj = self.bus.get_object("org.freedesktop.Notifications",
                                      "/org/freedesktop/Notifications")
            dbus.Interface(obj, "org.freedesktop.Notifications").Notify(
                "Nimbus Drive", dbus.UInt32(0), "io.github.nimbusdrive", title, body,
                dbus.Array([], signature="s"), dbus.Dictionary({}, signature="sv"), -1)
        except dbus.DBusException:
            print(f"{title}: {body}", file=sys.stderr)

    # ---- transfers ----

    def poll(self) -> None:
        if not self.mount.ready:
            return
        try:
            stats = self.rc.call("core/stats")
            queue = self.rc.call("vfs/queue", fs=f"{self.cfg['remote']}:").get("queue") or []
        except RcError:
            return
        downloads, uploads = {}, {}
        for t in stats.get("transferring") or []:
            entry = {"pct": t.get("percentage", 0), "size": t.get("size", 0),
                     "bytes": t.get("bytes", 0), "speed": t.get("speedAvg", 0)}
            (uploads if t.get("dstFs") else downloads)[t["name"]] = entry
        for q in queue:
            uploads.setdefault(q["name"], {"pct": 0, "size": q.get("size", 0), "bytes": 0,
                                           "speed": 0})
        with self.lock:
            for rel in self.requested:
                downloads.setdefault(rel, {"pct": 0, "size": 0, "bytes": 0, "speed": 0})
        touched = (set(downloads) ^ set(self.downloads)) | (set(uploads) ^ set(self.uploads))
        progress = set(downloads) | set(uploads)
        self.downloads, self.uploads = downloads, uploads
        if touched:
            mp = self.cfg.mount_path
            self.changed([str(mp / rel) for rel in touched])
        if touched or progress:
            self.summary_changed()

    # ---- path helpers ----

    def mount_rel(self, path: Path) -> str | None:
        try:
            rel = path.absolute().relative_to(self.cfg.mount_path)
        except ValueError:
            return None
        return C.normalize_rel(str(rel))

    def offline_folder_of(self, rel: str) -> str | None:
        return next((f for f in self.cfg.offline_folders() if C.is_under(rel, f)), None)

    # ---- status ----

    def status(self, path_str: str) -> str:
        """State of one path. A trailing "/" says the path is a directory, which spares
        a stat through the mount (file managers know it anyway)."""
        dir_hint = path_str.endswith("/") and len(path_str) > 1
        path = Path(path_str)
        rel = self.mount_rel(path)
        if rel is None:
            return self.mirror.status_of(path.absolute())
        if not rel or not self.mount.ready:
            return S.NONE
        folder = self.offline_folder_of(rel)
        if rel in self.uploads:
            return S.UPLOADING
        if rel in self.downloads:
            return S.DOWNLOADING
        # Never stat through the mount here: an uncached Drive listing can take a minute
        # and would freeze the D-Bus service. Without a hint, the cache tells dirs apart.
        if dir_hint or (self.cache and self.cache.is_dir(rel)):
            if folder:
                return S.SYNCING if self.mirror.current == folder else S.OFFLINE
            return S.NONE
        state = self.cache.state(rel) if self.cache else S.CLOUD
        if state == S.CLOUD and folder:
            return S.OFFLINE
        return state

    def summary(self) -> dict:
        disk = {}
        if self.mount.ready:
            try:
                disk = self.rc.call("vfs/stats", fs=f"{self.cfg['remote']}:").get("diskCache", {})
            except RcError:
                pass
        return {
            "version": __version__,
            "configured": self.cfg.configured,
            "remote": self.cfg["remote"],
            "mount": {"path": str(self.cfg.mount_path), "ready": self.mount.ready,
                      "error": self.mount.error},
            "mirror_root": str(self.cfg.mirror_path),
            "downloads": [{"name": k, **v} for k, v in sorted(self.downloads.items())],
            "uploads": [{"name": k, **v} for k, v in sorted(self.uploads.items())],
            "cache": {"bytes": disk.get("bytesUsed", 0), "files": disk.get("files", 0),
                      "max": self.cfg["cache_max_size"]},
            "mirror": self.mirror.summary(),
        }

    # ---- actions ----

    def download(self, paths: list[Path]) -> str:
        if not self.mount.ready:
            return "Google Drive не подключён"
        files = 0
        for p in paths:
            if self.mount_rel(p) is None:
                continue
            files += 1
            self.pool.submit(self._download_tree, p)
        return f"Скачиваю: {files}" if files else "Эти файлы не из Google Drive"

    def _download_tree(self, path: Path) -> None:
        if path.is_dir():
            for root, _dirs, names in os.walk(path):
                for n in names:
                    self.pool.submit(self._download_file, Path(root) / n)
        else:
            self._download_file(path)

    def _download_file(self, path: Path) -> None:
        rel = self.mount_rel(path)
        if rel is None or (self.cache and self.cache.state(rel) == S.CACHED):
            return
        with self.lock:
            self.requested[rel] = time.time()
        try:
            # Reading through the mount makes rclone fetch the file into its cache.
            with open(path, "rb") as f:
                while f.read(1 << 20):
                    pass
        except OSError as e:
            QTimer.singleShot(0, lambda: self.notify("Не удалось скачать", f"{path.name}: {e}"))
        finally:
            with self.lock:
                self.requested.pop(rel, None)

    def free_space(self, paths: list[Path]) -> str:
        if not self.mount.ready or self.cache is None:
            return "Google Drive не подключён"
        open_files = self._open_files()
        freed, skipped, changed = 0, 0, []
        for p in paths:
            rel = self.mount_rel(p)
            if rel is None:
                continue
            for item in list(self.cache.iter_cached(rel)):
                if (item in open_files or item in self.uploads or item in self.downloads
                        or self.cache.is_dirty(item)):
                    skipped += 1
                    continue
                freed += self.cache.evict(item)
                changed.append(str(self.cfg.mount_path / item))
        self.changed(changed)
        self.summary_changed()
        msg = f"Освобождено {human_size(freed)}"
        if skipped:
            msg += f"; пропущено файлов: {skipped} (открыты или ещё не загружены в облако)"
        return msg

    def _open_files(self) -> set[str]:
        """Remote-relative paths that some process currently has open in the mount."""
        prefix = str(self.cfg.mount_path) + "/"
        found = set()
        for fd_dir in Path("/proc").glob("[0-9]*/fd"):
            try:
                for fd in fd_dir.iterdir():
                    try:
                        target = os.readlink(fd)
                    except OSError:
                        continue
                    if target.startswith(prefix):
                        found.add(target[len(prefix):])
            except OSError:
                continue
        return found

    def set_offline(self, paths: list[Path], enabled: bool, remove_local: bool) -> str:
        folders = []
        for p in paths:
            rel = self.mount_rel(p)
            if rel is None:
                # Also accept paths inside the offline copy.
                try:
                    rel = C.normalize_rel(str(p.absolute().relative_to(self.cfg.mirror_path)))
                except ValueError:
                    continue
            if rel:
                folders.append(rel)
        if not folders:
            return "Выберите папки из Google Drive"
        current = self.cfg.offline_folders()
        msgs = []
        if enabled:
            for f in folders:
                if self.offline_folder_of(f):
                    continue
                # A parent folder replaces its sub-folders that were offline before.
                for sub in [c for c in current if C.is_under(c, f)]:
                    current.remove(sub)
                    self.mirror.remove(sub, trash_local=False)
                current.append(f)
                msgs.append(f"«{f}» будет доступна офлайн в {self.cfg.mirror_path / f}")
        else:
            for f in folders:
                if f in current:
                    current.remove(f)
                    msgs.append(self.mirror.remove(f, trash_local=remove_local))
        self.cfg["offline_folders"] = current
        self.cfg.save()
        self.mirror.apply_config(self.cfg)
        if enabled:
            for f in folders:
                if f in current:
                    self.mirror.sync(f)
        self.summary_changed()
        return "\n".join(msgs) or "Ничего не изменилось"


def main() -> int:
    if rclone_version() < MIN_RCLONE:
        print(f"Нужен rclone {MIN_RCLONE[0]}.{MIN_RCLONE[1]} или новее: https://rclone.org/install/",
              file=sys.stderr)
        return 1
    app = QCoreApplication(sys.argv)
    app.setApplicationName("nimbus-drive")
    DBusQtMainLoop(set_as_default=True)
    try:
        name = dbus.service.BusName(DBUS_NAME, dbus.SessionBus(), do_not_queue=True)
    except dbus.exceptions.NameExistsException:
        print("Nimbus Drive уже запущен", file=sys.stderr)
        return 1
    daemon = Daemon()
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Python handles signals only when it runs; wake it up regularly.
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(500)
    daemon.start()
    code = app.exec()
    daemon.shutdown()
    del name
    return code
