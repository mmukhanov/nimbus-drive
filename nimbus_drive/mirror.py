"""Offline folders: real local copies kept in sync with `rclone bisync`."""

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from PyQt6.QtCore import QFile, QObject, QProcess, QTimer, pyqtSignal

from . import config as C
from . import status as S

CONFLICT_RE = re.compile(r"\.conflict\d+(\.|$)")

# Never synced: editor lock/temp files, Dolphin view settings, partial downloads.
FILTERS = """\
- .~lock.*#
- ~$*
- *.swp
- *.tmp
- *.part
- *.partial
- *.crdownload
- .directory
- .Trash-*/**
- .nimbus-*
"""


def folder_id(folder: str) -> str:
    return hashlib.sha1(folder.encode()).hexdigest()[:12]


def workdir_for(folder: str) -> Path:
    # One bisync workdir per folder, so removing a folder cleanly drops its listings.
    return C.BISYNC_WORKDIR / folder_id(folder)


class MirrorManager(QObject):
    changed = pyqtSignal(list)        # local paths; a trailing "/" means "everything below"
    summaryChanged = pyqtSignal()
    notify = pyqtSignal(str, str)

    def __init__(self, cfg: C.Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.state = self._load_state()
        self.queue: list[tuple[str, bool]] = []
        self.current: str | None = None
        self.current_started = 0.0
        self.proc: QProcess | None = None
        self.paused = False
        self.discard_result = False  # set when we kill a run on purpose
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sync_all)
        self.apply_config(cfg)

    # ---- state ----

    def _load_state(self) -> dict:
        try:
            return json.loads(C.MIRROR_STATE_FILE.read_text())
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        C.STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = C.MIRROR_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
        tmp.replace(C.MIRROR_STATE_FILE)

    def folder_state(self, folder: str) -> dict:
        return self.state.setdefault(folder, {
            "initialized": False, "last_success": 0, "error": "", "needs_force": False,
        })

    def apply_config(self, cfg: C.Config) -> None:
        self.cfg = cfg
        for folder in list(self.state):
            if folder not in cfg.offline_folders():
                del self.state[folder]
        self._save_state()
        minutes = max(1, int(cfg["sync_interval_minutes"]))
        self.timer.start(minutes * 60_000)

    def local_path(self, folder: str) -> Path:
        return self.cfg.mirror_path / folder

    # ---- scheduling ----

    def sync_all(self) -> None:
        if self.paused or not self.cfg.configured:
            return
        for folder in self.cfg.offline_folders():
            self.sync(folder)

    def sync(self, folder: str, force: bool = False) -> None:
        if folder == self.current or any(f == folder for f, _ in self.queue):
            if force:
                self.queue = [(f, force if f == folder else fl) for f, fl in self.queue]
            return
        self.queue.append((folder, force))
        QTimer.singleShot(0, self._next)

    def _next(self) -> None:
        if self.proc is not None or not self.queue:
            return
        folder, force = self.queue.pop(0)
        if folder not in self.cfg.offline_folders():
            return self._next()
        self._start(folder, force)

    def _start(self, folder: str, force: bool) -> None:
        st = self.folder_state(folder)
        local = self.local_path(folder)
        local.mkdir(parents=True, exist_ok=True)
        workdir = workdir_for(folder)
        workdir.mkdir(parents=True, exist_ok=True)
        filters = C.STATE_DIR / "bisync-filters.txt"
        filters.write_text(FILTERS)

        remote = f"{self.cfg['remote']}:{folder}"
        # bisync names its lock and listing files after both paths joined together;
        # past the 255-byte file name limit it cannot run at all.
        session = (remote.replace(":", "_", 1) + ".." + str(local).lstrip("/")).replace("/", "_")
        if len(session.encode()) > 225:
            st["error"] = ("Слишком длинный путь для синхронизации. Выберите папку повыше "
                           "или укажите более короткую папку для офлайн-копий.")
            self._save_state()
            self._emit_folder(folder)
            self.summaryChanged.emit()
            QTimer.singleShot(0, self._next)
            return

        args = [
            "bisync", remote, str(local),
            "--workdir", str(workdir),
            "--filters-file", str(filters),
            "--resilient", "--recover", "--max-lock", "2m",
            "--conflict-resolve", "newer", "--conflict-loser", "num",
            "--conflict-suffix", "conflict", "--suffix-keep-extension",
            "--create-empty-src-dirs", "--compare", "size,modtime",
            "--fast-list", "--drive-skip-gdocs",
            "--log-level", "INFO",
        ]
        if not st["initialized"]:
            # First run merges both sides and never deletes anything.
            args += ["--resync", "--resync-mode", "newer"]
        if force:
            args.append("--force")

        self.current = folder
        self.current_started = time.time()
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.finished.connect(lambda code, _status, f=folder: self._finished(f, code))
        self.proc.start("rclone", args)
        self._emit_folder(folder)
        self.summaryChanged.emit()

    def _finished(self, folder: str, code: int) -> None:
        output = bytes(self.proc.readAll()).decode(errors="replace")
        self.proc.deleteLater()
        self.proc = None
        self.current = None
        (C.STATE_DIR / "last-bisync.log").write_text(output)
        if self.discard_result:
            self.discard_result = False
            self.summaryChanged.emit()
            QTimer.singleShot(0, self._next)
            return
        st = self.folder_state(folder)

        if code == 0:
            st.update(initialized=True, last_success=self.current_started,
                      error="", needs_force=False)
            self._report_conflicts(folder)
        else:
            st["error"], st["needs_force"] = explain_bisync_error(output)
            if "--resync" in output and "Must run --resync" in output and st["initialized"]:
                # Listings are unusable; a resync merges both sides without deleting.
                st["initialized"] = False
                self.queue.insert(0, (folder, False))
            elif self.cfg["notifications"]:
                self.notify.emit(f"Не удалось синхронизировать «{folder}»", st["error"])
        self._save_state()
        self._emit_folder(folder)
        self.summaryChanged.emit()
        QTimer.singleShot(0, self._next)

    def _report_conflicts(self, folder: str) -> None:
        if not self.cfg["notifications"]:
            return
        found = []
        for p in self.local_path(folder).rglob("*"):
            if CONFLICT_RE.search(p.name):
                try:
                    if p.stat().st_ctime >= self.current_started - 5:
                        found.append(p.name)
                except OSError:
                    pass
        if found:
            names = ", ".join(found[:3]) + (f" и ещё {len(found) - 3}" if len(found) > 3 else "")
            self.notify.emit("Конфликт версий",
                             f"Файл изменён и здесь, и в облаке. Сохранены обе версии: {names}")

    def _emit_folder(self, folder: str) -> None:
        local = self.local_path(folder)
        mount = self.cfg.mount_path / folder
        self.changed.emit([str(local), str(local) + "/", str(mount), str(mount) + "/"])

    def reset_all(self) -> None:
        if self.proc is not None:
            self.discard_result = True
            self.proc.kill()
            self.proc.waitForFinished(5000)
        self.queue.clear()
        self.state.clear()
        self._save_state()
        shutil.rmtree(C.BISYNC_WORKDIR, ignore_errors=True)

    # ---- add/remove ----

    def remove(self, folder: str, trash_local: bool) -> str:
        if self.current == folder and self.proc is not None:
            self.discard_result = True
            self.proc.kill()
            self.proc.waitForFinished(5000)
        self.queue = [(f, fl) for f, fl in self.queue if f != folder]
        self.state.pop(folder, None)
        self._save_state()
        shutil.rmtree(workdir_for(folder), ignore_errors=True)
        msg = f"«{folder}» больше не хранится офлайн."
        local = self.local_path(folder)
        if trash_local and local.exists():
            if QFile.moveToTrash(str(local)):
                msg += " Локальная копия перемещена в корзину."
            else:
                msg += f" Не удалось переместить в корзину: {local}"
        self._emit_folder(folder)
        self.summaryChanged.emit()
        return msg

    # ---- status ----

    def status_of(self, path: Path) -> str:
        try:
            rel = C.normalize_rel(str(path.relative_to(self.cfg.mirror_path)))
        except ValueError:
            return S.NONE
        folder = next((f for f in self.cfg.offline_folders() if C.is_under(rel, f)), None)
        if folder is None:
            return S.NONE
        st = self.folder_state(folder)
        running = self.current == folder
        if rel == folder:
            if running:
                return S.SYNCING
            return S.ERROR if st["error"] else S.OFFLINE
        if CONFLICT_RE.search(path.name):
            return S.CONFLICT
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return S.NONE
        if path.is_dir():
            return S.SYNCING if running else S.OFFLINE
        if not st["initialized"] or mtime > st["last_success"]:
            return S.SYNCING if running else S.PENDING
        return S.OFFLINE

    def summary(self) -> dict:
        folders = []
        for f in self.cfg.offline_folders():
            st = self.folder_state(f)
            folders.append({
                "folder": f, "local": str(self.local_path(f)),
                "running": self.current == f, "queued": any(q == f for q, _ in self.queue),
                "last_success": st["last_success"], "error": st["error"],
                "needs_force": st["needs_force"],
            })
        return {"running": self.current, "paused": self.paused, "folders": folders}


def explain_bisync_error(output: str) -> tuple[str, bool]:
    """Turn rclone bisync output into a short message for people. Returns (message, needs_force)."""
    low = output.lower()
    if "too many deletes" in low:
        return ("Слишком много удалений за раз — синхронизация остановлена для защиты данных. "
                "Проверьте папку и подтвердите в меню трея.", True)
    if "directory not found" in low or ("not found" in low and "path1" in low):
        return ("Папка не найдена в облаке (удалена или переименована).", False)
    if "couldn't connect" in low or "no such host" in low or "network is unreachable" in low:
        return ("Нет связи с Google Drive. Повторю позже.", False)
    if "invalid_grant" in low or ("token" in low and "expired" in low):
        return ("Доступ к аккаунту истёк — переподключите аккаунт в настройках.", False)
    lines = [l for l in output.splitlines() if "ERROR" in l]
    return ((lines[-1].split("ERROR", 1)[-1].strip(" :") if lines else "неизвестная ошибка")[:300],
            False)
