"""Tray icon and the main window: activity, offline folders, account, settings."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.pyqt6 import DBusQtMainLoop
from PyQt6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSystemTrayIcon, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import HOMEPAGE, __version__
from . import config as C
from .client import DaemonClient

AUTOSTART_FILE = Path(os.path.expanduser(os.environ.get("XDG_CONFIG_HOME", "~/.config"))) \
    / "autostart" / "nimbus-drive-tray.desktop"
CLIENT_ID_GUIDE = HOMEPAGE + "/blob/main/docs/google-client-id.md"


def icon(name: str) -> QIcon:
    themed = QIcon.fromTheme(name)
    if not themed.isNull():
        return themed
    local = Path(__file__).resolve().parent.parent / "data/icons/hicolor/scalable"
    for sub in ("apps", "emblems"):
        f = local / sub / f"{name}.svg"
        if f.exists():
            return QIcon(str(f))
    return QIcon()


# Overall state (badge from overall()) -> tray icon state.
TRAY_STATES = {
    None: "ok",
    "nimbusdrive-syncing": "sync",
    "nimbusdrive-pending": "paused",
    "nimbusdrive-conflict": "error",
    "nimbusdrive-error": "error",
}
TRAY_ICON_DIR = Path(__file__).resolve().parent / "icons"


def dark_theme() -> bool:
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme != Qt.ColorScheme.Unknown:
        return scheme == Qt.ColorScheme.Dark
    return QGuiApplication.palette().window().color().lightness() < 128


def tray_icon(state: str) -> QIcon:
    """Black icon for light panels, white for dark ones. Built from pixmaps so the tray
    host gets image data, not an icon name it would have to find in its own theme."""
    f = TRAY_ICON_DIR / f"tray-{state}-{'dark' if dark_theme() else 'light'}.svg"
    src, out = QIcon(str(f)), QIcon()
    for size in (16, 22, 24, 32, 48, 64):
        out.addPixmap(src.pixmap(size, size))
    return out


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def ago(ts: float) -> str:
    if not ts:
        return "not synced yet"
    d = time.time() - ts
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return time.strftime("%d.%m %H:%M", time.localtime(ts))


def drive_remotes() -> list[str]:
    try:
        out = subprocess.run(["rclone", "listremotes", "--long"], capture_output=True,
                             text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.split(":")[0] for line in out.splitlines() if line.split()[-1:] == ["drive"]]


def uses_shared_client_id(remote: str) -> bool:
    """True if the remote relies on rclone's shared OAuth client, which Google is retiring."""
    try:
        out = subprocess.run(["rclone", "config", "dump"], capture_output=True, text=True,
                             timeout=20).stdout
        return not json.loads(out).get(remote, {}).get("client_id")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


class Summary(QObject):
    """Holds the latest daemon summary and tells the widgets when it changes."""

    changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.client = DaemonClient()
        self.data: dict = {}
        self.client.on_summary(self._set)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)  # catches daemon (re)starts; live updates come via D-Bus
        self.refresh()

    def refresh(self):
        try:
            data = self.client.summary() if self.client.running() else {}
        except dbus.DBusException:
            data = {}
        self._set(data)

    def _set(self, data: dict):
        self.data = data
        self.changed.emit(data)


def overall(data: dict) -> tuple[str, str | None]:
    """Text for the tray tooltip and the badge for the tray icon."""
    if not data:
        return "The Nimbus Drive service is not running", "nimbusdrive-error"
    if not data["configured"]:
        return "No Google account connected", "nimbusdrive-error"
    if not data["mount"]["ready"]:
        return data["mount"]["error"] or "Connecting to Google Drive…", \
            "nimbusdrive-error" if data["mount"]["error"] else "nimbusdrive-pending"
    errors = [f for f in data["mirror"]["folders"] if f["error"]]
    downs, ups = data["downloads"], data["uploads"]
    running = data["mirror"]["running"]
    if downs or ups or running:
        parts = []
        if downs:
            parts.append(f"downloading {len(downs)}")
        if ups:
            parts.append(f"uploading {len(ups)}")
        if running:
            parts.append(f"syncing \"{running}\"")
        text = ", ".join(parts)
        return text[0].upper() + text[1:], "nimbusdrive-syncing"
    if errors:
        return f"Sync error: {errors[0]['folder']}", "nimbusdrive-conflict"
    if data["mirror"]["paused"]:
        return "Sync paused", "nimbusdrive-pending"
    return "Up to date", None


# ---------------------------------------------------------------- activity tab

class ActivityTab(QWidget):
    def __init__(self, summary: Summary):
        super().__init__()
        self.summary = summary
        self.status = QLabel()
        self.status.setWordWrap(True)
        f = self.status.font()
        f.setPointSizeF(f.pointSizeF() * 1.15)
        f.setBold(True)
        self.status.setFont(f)
        self.cache = QLabel()
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        open_btn = QPushButton(icon("folder-cloud"), "Open Google Drive")
        open_btn.clicked.connect(lambda: self._open("path"))
        offline_btn = QPushButton(icon("folder"), "Offline folders")
        offline_btn.clicked.connect(lambda: self._open("mirror_root"))
        self.sync_btn = QPushButton(icon("view-refresh"), "Sync now")
        self.sync_btn.clicked.connect(self._sync)
        buttons = QHBoxLayout()
        for b in (open_btn, offline_btn, self.sync_btn):
            buttons.addWidget(b)
        buttons.addStretch()

        lay = QVBoxLayout(self)
        lay.addWidget(self.status)
        lay.addWidget(self.cache)
        lay.addWidget(self.list, 1)
        lay.addLayout(buttons)
        summary.changed.connect(self.update_view)
        self.update_view(summary.data)

    def _open(self, key: str):
        d = self.summary.data
        path = d.get("mount", {}).get("path") if key == "path" else d.get("mirror_root")
        if path:
            if key == "mirror_root":
                Path(path).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _sync(self):
        try:
            self.summary.client.sync_now()
        except dbus.DBusException as e:
            QMessageBox.warning(self, "Nimbus Drive", str(e))

    def _row(self, text: str, icon_name: str, pct: float | None = None, button=None):
        item = QListWidgetItem(self.list)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 2, 4, 2)
        ic = QLabel()
        ic.setPixmap(icon(icon_name).pixmap(20, 20))
        h.addWidget(ic)
        lbl = QLabel(text)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(lbl, 1)
        if pct is not None:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(pct))
            bar.setMaximumWidth(140)
            h.addWidget(bar)
        if button:
            h.addWidget(button)
        item.setSizeHint(w.sizeHint())
        self.list.setItemWidget(item, w)

    def update_view(self, d: dict):
        text, _ = overall(d)
        self.status.setText(text)
        self.list.clear()
        if not d:
            self.cache.setText("Start it with: systemctl --user start nimbus-drive")
            return
        c = d["cache"]
        self.cache.setText(f"On this computer: {human_size(c['bytes'])} (limit {c['max']}) · "
                           f"account {d['remote'] or '—'}")
        for t in d["downloads"]:
            size = f" · {human_size(t['size'])}" if t["size"] else ""
            self._row(f"{t['name']}{size}", "nimbusdrive-downloading", t["pct"])
        for t in d["uploads"]:
            self._row(t["name"], "nimbusdrive-uploading", t["pct"])
        for f in d["mirror"]["folders"]:
            if f["running"]:
                self._row(f"{f['folder']} — syncing…", "nimbusdrive-syncing")
            elif f["error"]:
                btn = None
                if f["needs_force"]:
                    btn = QPushButton("Confirm")
                    btn.clicked.connect(lambda _=False, folder=f["folder"]: self._force(folder))
                self._row(f"{f['folder']} — {f['error']}", "nimbusdrive-error", button=btn)
            else:
                self._row(f"{f['folder']} — offline, synced {ago(f['last_success'])}", "nimbusdrive-offline")
        if self.list.count() == 0:
            self._row("No transfers right now. No offline folders chosen.", "nimbusdrive-cached")

    def _force(self, folder: str):
        if QMessageBox.question(
                self, "Confirm deletions",
                f"Many files were deleted on one side of \"{folder}\". If you did this, "
                "confirm and the deletions will be applied to the other side too.") \
                == QMessageBox.StandardButton.Yes:
            self.summary.client.force_sync(folder)


# ---------------------------------------------------------------- offline folders tab

class _Lister(QRunnable):
    """Lists sub-folders through the mount in a worker thread (Drive listings can be slow)."""

    class Signals(QObject):
        done = pyqtSignal(object, list, str)

    def __init__(self, item, path: Path):
        super().__init__()
        self.item, self.path = item, path
        self.signals = self.Signals()

    def run(self):
        try:
            names = sorted((e.name for e in os.scandir(self.path)
                            if e.is_dir(follow_symlinks=False)), key=str.casefold)
            self.signals.done.emit(self.item, names, "")
        except OSError as e:
            self.signals.done.emit(self.item, [], str(e))


class OfflineTab(QWidget):
    REL = Qt.ItemDataRole.UserRole
    LOADED = Qt.ItemDataRole.UserRole + 1

    def __init__(self, summary: Summary):
        super().__init__()
        self.summary = summary
        self.cfg = C.Config.load()
        self.pool = QThreadPool(self)
        info = QLabel(
            "Checked folders are kept on this computer in full and synced both ways, so they "
            "work without internet. Everything else stays visible in Google Drive and "
            "downloads when you open it.")
        info.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemChanged.connect(self._changed)
        self.where = QLabel()
        self.apply_btn = QPushButton(icon("dialog-ok-apply"), "Apply")
        self.apply_btn.clicked.connect(self.apply)
        reload_btn = QPushButton(icon("view-refresh"), "Refresh")
        reload_btn.clicked.connect(self.reload)
        row = QHBoxLayout()
        row.addWidget(self.where, 1)
        row.addWidget(reload_btn)
        row.addWidget(self.apply_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.tree, 1)
        lay.addLayout(row)
        self.reload()

    def reload(self):
        self.cfg = C.Config.load()
        self.selected = set(self.cfg.offline_folders())
        self.where.setText(f"Offline copies: {self.cfg.mirror_path}")
        self.tree.clear()
        root = self.tree.invisibleRootItem()
        self._load(root, "")

    def _load(self, item, rel: str):
        placeholder = QTreeWidgetItem(["Loading…"])
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        if item is self.tree.invisibleRootItem():
            self.tree.addTopLevelItem(placeholder)
        else:
            item.addChild(placeholder)
        job = _Lister(item, self.cfg.mount_path / rel)
        job.signals.done.connect(self._loaded)
        self.pool.start(job)

    def _loaded(self, item, names: list, error: str):
        try:
            parent_rel = "" if item is self.tree.invisibleRootItem() else item.data(0, self.REL)
        except RuntimeError:
            return  # tree was rebuilt meanwhile
        item.takeChildren()
        if error:
            err = QTreeWidgetItem([f"Cannot open: {error}"])
            err.setFlags(Qt.ItemFlag.NoItemFlags)
            item.addChild(err)
            return
        self.tree.blockSignals(True)
        for name in names:
            rel = f"{parent_rel}/{name}" if parent_rel else name
            child = QTreeWidgetItem([name])
            child.setIcon(0, icon("folder"))
            child.setData(0, self.REL, rel)
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            inherited = any(C.is_under(rel, s) and rel != s for s in self.selected)
            child.setCheckState(0, Qt.CheckState.Checked if rel in self.selected or inherited
                                else Qt.CheckState.Unchecked)
            if inherited:
                child.setDisabled(True)
            child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            item.addChild(child)
        self.tree.blockSignals(False)

    def _expand(self, item):
        if not item.data(0, self.LOADED):
            item.setData(0, self.LOADED, True)
            self._load(item, item.data(0, self.REL))

    def _changed(self, item, _col):
        rel = item.data(0, self.REL)
        if item.checkState(0) == Qt.CheckState.Checked:
            self.selected = {s for s in self.selected if not C.is_under(s, rel)} | {rel}
        else:
            self.selected.discard(rel)
        self.tree.blockSignals(True)
        self._propagate(item, item.checkState(0) == Qt.CheckState.Checked)
        self.tree.blockSignals(False)

    def _propagate(self, item, checked: bool):
        for i in range(item.childCount()):
            ch = item.child(i)
            if ch.data(0, self.REL) is None:
                continue
            ch.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            ch.setDisabled(checked)
            self._propagate(ch, checked)

    def apply(self):
        before = set(C.Config.load().offline_folders())
        added = sorted(self.selected - before)
        removed = sorted(before - self.selected)
        if not added and not removed:
            return
        mp = self.cfg.mount_path
        client = self.summary.client
        try:
            msgs = []
            if removed:
                answer = QMessageBox.question(
                    self, "Stop keeping offline",
                    "These folders stay in the cloud:\n  " + "\n  ".join(removed) +
                    "\n\nMove their local copies to the Trash?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.No)
                if answer == QMessageBox.StandardButton.Cancel:
                    return
                msgs.append(client.set_offline([str(mp / r) for r in removed], False,
                                               answer == QMessageBox.StandardButton.Yes))
            if added:
                msgs.append(client.set_offline([str(mp / a) for a in added], True))
            QMessageBox.information(self, "Offline folders", "\n".join(msgs))
        except dbus.DBusException as e:
            QMessageBox.warning(self, "Nimbus Drive", f"The service did not respond: {e}")
        self.reload()


# ---------------------------------------------------------------- account tab

class ConnectDialog(QDialog):
    """Creates or re-authorizes an rclone Google Drive remote with the user's own OAuth client."""

    def __init__(self, parent, remote: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Connect Google Drive")
        self.resize(560, 480)
        self.update_existing = bool(remote)
        self.name = QLineEdit(remote or "gdrive")
        self.name.setReadOnly(self.update_existing)
        self.client_id = QLineEdit()
        self.client_secret = QLineEdit()
        self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        guide = QLabel(
            "To sign in to Google, an app needs a client ID. rclone's shared one is being "
            "retired by Google during 2026, so create your own once. It is free but takes "
            "30–60 minutes the first time — follow the "
            f"<a href='{CLIENT_ID_GUIDE}'><b>step-by-step guide</b></a>."
            "<p>In short: in Google Cloud Console enable the Google Drive API, set up the "
            "OAuth consent screen (<i>External</i>), add the <code>.../auth/drive</code> "
            "scope and yourself as a test user, create a <i>Desktop app</i> client and paste "
            "its ID and secret below.</p>"
            "<p>While the app is in <i>Testing</i>, Google drops the sign-in every 7 days and "
            "you reconnect here with one click. Publishing it removes that but needs a home "
            "page and privacy policy on a domain you own — the guide shows a free way.</p>"
            "<p>Google warns that the app is unverified: expected for your own app, choose "
            "<i>Advanced → Go to …</i>.</p>")
        guide.setWordWrap(True)
        guide.setOpenExternalLinks(True)
        form = QFormLayout()
        form.addRow("Connection name:", self.name)
        form.addRow("Client ID:", self.client_id)
        form.addRow("Client secret:", self.client_secret)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Your browser opens for the Google sign-in when you press Sign in.")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.login = self.buttons.addButton("Sign in with browser",
                                            QDialogButtonBox.ButtonRole.ActionRole)
        self.login.clicked.connect(self.start)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(guide)
        lay.addLayout(form)
        lay.addWidget(self.log, 1)
        lay.addWidget(self.buttons)
        self.proc = None

    def start(self):
        from PyQt6.QtCore import QProcess
        name = self.name.text().strip()
        cid, secret = self.client_id.text().strip(), self.client_secret.text().strip()
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            QMessageBox.warning(self, "Connect", "Use Latin letters, digits, - and _ in the name.")
            return
        if not cid or not secret:
            if QMessageBox.question(
                    self, "No client ID",
                    "Without your own client ID this connection stops working when Google "
                    "retires rclone's shared one. Continue anyway?") \
                    != QMessageBox.StandardButton.Yes:
                return
        params = ["scope=drive"]
        if cid and secret:
            params += [f"client_id={cid}", f"client_secret={secret}"]
        if self.update_existing:
            args = ["config", "update", name, *params, "config_refresh_token=true"]
        else:
            if name in drive_remotes():
                QMessageBox.warning(self, "Connect", f"A connection named \"{name}\" already exists.")
                return
            args = ["config", "create", name, "drive", *params]
        self.login.setEnabled(False)
        self.log.setPlainText("Sign in to your Google account in the browser…\n")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyRead.connect(self._read)
        self.proc.finished.connect(self._done)
        self.proc.start("rclone", args)

    def _read(self):
        text = bytes(self.proc.readAll()).decode(errors="replace")
        # Never echo the config block rclone prints at the end: it contains the token.
        self.log.appendPlainText("\n".join(l for l in text.splitlines()
                                           if "token" not in l.lower() and "secret" not in l))

    def _done(self, code, _status):
        self.login.setEnabled(True)
        if code == 0:
            self.log.appendPlainText("\nDone: the account is connected.")
            self.accept()
        else:
            self.log.appendPlainText(f"\nThat did not work (code {code}). Check the client ID and secret.")


class AccountTab(QWidget):
    def __init__(self, summary: Summary, on_saved):
        super().__init__()
        self.summary = summary
        self.on_saved = on_saved
        self.remote = QComboBox()
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #c0392b;")
        new_btn = QPushButton(icon("list-add-user"), "Connect another account…")
        new_btn.clicked.connect(lambda: self.connect_account(""))
        self.reauth_btn = QPushButton(icon("view-refresh"), "Reconnect with your own client ID…")
        self.reauth_btn.clicked.connect(lambda: self.connect_account(self.remote.currentText()))
        use_btn = QPushButton(icon("dialog-ok-apply"), "Use this account")
        use_btn.clicked.connect(self.use_remote)
        form = QFormLayout()
        form.addRow("rclone connection:", self.remote)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.warning)
        for b in (use_btn, self.reauth_btn, new_btn):
            lay.addWidget(b)
        lay.addStretch()
        self.remote.currentTextChanged.connect(self.check_remote)
        self.refresh()

    def refresh(self):
        cfg = C.Config.load()
        self.remote.blockSignals(True)
        self.remote.clear()
        self.remote.addItems(drive_remotes())
        if cfg["remote"]:
            self.remote.setCurrentText(cfg["remote"])
        self.remote.blockSignals(False)
        self.check_remote(self.remote.currentText())

    def check_remote(self, name: str):
        shared = bool(name) and uses_shared_client_id(name)
        self.warning.setText(
            "⚠ This connection signs in with rclone's shared client ID, which Google is "
            "retiring during 2026. Once it is retired, Google Drive stops connecting. "
            "Reconnect with your own client ID (free, done once; the guide takes 30–60 "
            "minutes the first time) and it keeps working."
            if shared else "")
        self.reauth_btn.setVisible(bool(name))

    def connect_account(self, remote: str):
        if ConnectDialog(self, remote).exec():
            self.refresh()
            if not remote:
                self.use_remote()

    def use_remote(self):
        name = self.remote.currentText()
        if not name:
            return
        cfg = C.Config.load()
        cfg["remote"] = name
        cfg.save()
        self.on_saved()


# ---------------------------------------------------------------- settings tab

class SettingsTab(QWidget):
    def __init__(self, on_saved):
        super().__init__()
        self.on_saved = on_saved
        cfg = C.Config.load()
        self.mount = QLineEdit(cfg["mount_point"])
        self.mirror = QLineEdit(cfg["mirror_root"])
        self.cache = QSpinBox()
        self.cache.setRange(1, 4096)
        self.cache.setSuffix(" GB")
        self.cache.setValue(_parse_gb(cfg["cache_max_size"]))
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setSuffix(" days")
        self.days.setValue(max(1, _parse_hours(cfg["cache_max_age"]) // 24))
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setSuffix(" min")
        self.interval.setValue(int(cfg["sync_interval_minutes"]))
        self.notify = QCheckBox("Notify me about conflicts and errors")
        self.notify.setChecked(bool(cfg["notifications"]))
        self.autostart = QCheckBox("Show the tray icon when I log in")
        self.autostart.setChecked(AUTOSTART_FILE.exists())

        form = QFormLayout()
        form.addRow("Google Drive folder:", self._with_browse(self.mount))
        form.addRow("Offline copies:", self._with_browse(self.mirror))
        form.addRow("Space for downloaded files:", self.cache)
        form.addRow("Keep downloaded files for:", self.days)
        form.addRow("Sync offline folders every:", self.interval)
        save = QPushButton(icon("document-save"), "Save")
        save.clicked.connect(self.save)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.notify)
        lay.addWidget(self.autostart)
        lay.addStretch()
        about = QLabel(f"Nimbus Drive {__version__}, built on rclone · "
                       f"<a href='{HOMEPAGE}'>GitHub</a>")
        about.setOpenExternalLinks(True)
        lay.addWidget(about)
        lay.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)

    def _with_browse(self, edit: QLineEdit) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        b = QPushButton(icon("document-open-folder"), "")
        b.clicked.connect(lambda: self._browse(edit))
        h.addWidget(b)
        return w

    def _browse(self, edit: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder",
                                             os.path.expanduser(edit.text()))
        if d:
            home = str(Path.home())
            edit.setText("~" + d[len(home):] if d.startswith(home + "/") else d)

    def save(self):
        cfg = C.Config.load()
        new_mount = os.path.expanduser(self.mount.text().strip())
        new_mirror = os.path.expanduser(self.mirror.text().strip())
        if not new_mount or not new_mirror:
            return
        a, b = Path(new_mount).absolute(), Path(new_mirror).absolute()
        if a == b or a in b.parents or b in a.parents:
            QMessageBox.warning(self, "Settings", "The Google Drive folder and the offline "
                                                   "copies must not be inside each other.")
            return
        if cfg.mirror_path != b and cfg.offline_folders() and cfg.mirror_path.exists():
            QMessageBox.information(
                self, "Settings",
                f"Offline folders will be downloaded again to {b}. The old copy stays in "
                f"{cfg.mirror_path} — delete it yourself once everything is in place.")
        cfg.update({
            "mount_point": self.mount.text().strip(),
            "mirror_root": self.mirror.text().strip(),
            "cache_max_size": f"{self.cache.value()}G",
            "cache_max_age": f"{self.days.value() * 24}h",
            "sync_interval_minutes": self.interval.value(),
            "notifications": self.notify.isChecked(),
        })
        cfg.save()
        set_autostart(self.autostart.isChecked())
        self.on_saved()


def _parse_gb(s: str) -> int:
    s = str(s).strip().upper()
    mult = {"M": 1 / 1024, "G": 1, "T": 1024}
    try:
        return max(1, int(float(s[:-1]) * mult[s[-1]]) if s[-1] in mult else int(float(s) / 2**30))
    except (ValueError, IndexError):
        return 10


def _parse_hours(s: str) -> int:
    s = str(s).strip().lower()
    try:
        if s.endswith("h"):
            return int(float(s[:-1]))
        if s.endswith("d"):
            return int(float(s[:-1]) * 24)
    except ValueError:
        pass
    return 720


def set_autostart(enabled: bool):
    if enabled:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        exe = shutil.which("nimbus-drive") or "nimbus-drive"
        AUTOSTART_FILE.write_text(
            "[Desktop Entry]\nType=Application\nName=Nimbus Drive\n"
            f"Exec={exe} tray\nIcon=io.github.nimbusdrive\nX-GNOME-Autostart-enabled=true\n"
            "NoDisplay=true\n")
    elif AUTOSTART_FILE.exists():
        AUTOSTART_FILE.unlink()


# ---------------------------------------------------------------- window + tray

class MainWindow(QWidget):
    def __init__(self, summary: Summary):
        super().__init__()
        self.summary = summary
        self.setWindowTitle("Nimbus Drive")
        self.setWindowIcon(icon("io.github.nimbusdrive"))
        self.resize(680, 560)
        self.tabs = QTabWidget()
        self.activity = ActivityTab(summary)
        self.offline = OfflineTab(summary)
        self.account = AccountTab(summary, self.saved)
        self.settings = SettingsTab(self.saved)
        self.tabs.addTab(self.activity, icon("nimbusdrive-syncing"), "Activity")
        self.tabs.addTab(self.offline, icon("nimbusdrive-offline"), "Offline folders")
        self.tabs.addTab(self.account, icon("im-user"), "Account")
        self.tabs.addTab(self.settings, icon("configure"), "Settings")
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)

    def saved(self):
        try:
            if self.summary.client.running():
                self.summary.client.reload()
            else:
                subprocess.run(["systemctl", "--user", "start", "nimbus-drive.service"])
        except dbus.DBusException as e:
            QMessageBox.warning(self, "Nimbus Drive", str(e))
        QTimer.singleShot(1500, self.offline.reload)
        QTimer.singleShot(1000, self.summary.refresh)

    def show_tab(self, index: int):
        self.tabs.setCurrentIndex(index)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        # Closing the window keeps the tray running, like other sync clients.
        if QSystemTrayIcon.isSystemTrayAvailable() and getattr(self, "has_tray", False):
            event.ignore()
            self.hide()
        else:
            event.accept()


class Tray(QSystemTrayIcon):
    def __init__(self, summary: Summary, window: MainWindow):
        super().__init__(tray_icon("sync"))
        self.summary, self.window = summary, window
        self.state = "sync"
        # Follow KDE switching between light and dark themes.
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._retheme)
        QApplication.instance().installEventFilter(self)
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        summary.changed.connect(self.update_view)
        self.update_view(summary.data)

    def eventFilter(self, obj, event):
        if obj is QApplication.instance() and event.type() == QEvent.Type.ApplicationPaletteChange:
            self._retheme()
        return False

    def _retheme(self, *_):
        self.setIcon(tray_icon(self.state))

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.window.isVisible():
                self.window.hide()
            else:
                self.window.show_tab(0)

    def update_view(self, d: dict):
        text, badge = overall(d)
        state = TRAY_STATES.get(badge, "ok")
        if state != self.state:
            self.state = state
            self.setIcon(tray_icon(state))
        lines = [text]
        for t in (d.get("downloads") or [])[:5]:
            lines.append(f"↓ {Path(t['name']).name} — {t['pct']}%")
        for t in (d.get("uploads") or [])[:5]:
            lines.append(f"↑ {Path(t['name']).name} — {t['pct']}%")
        self.setToolTip("Nimbus Drive\n" + "\n".join(lines))
        self._build_menu(d, lines)

    def _build_menu(self, d: dict, lines: list[str]):
        m = self.menu
        m.clear()
        for line in lines:
            a = m.addAction(line)
            a.setEnabled(False)
        m.addSeparator()
        if not d:
            m.addAction(icon("media-playback-start"), "Start the service", lambda: subprocess.run(
                ["systemctl", "--user", "start", "nimbus-drive.service"]))
        else:
            mount = d["mount"]["path"]
            m.addAction(icon("folder-cloud"), "Open Google Drive",
                        lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(mount)))
            if d["mirror"]["folders"]:
                root = d["mirror_root"]
                m.addAction(icon("folder"), "Open offline folders",
                            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(root)))
                m.addAction(icon("view-refresh"), "Sync now",
                            self.summary.client.sync_now)
                paused = d["mirror"]["paused"]
                m.addAction(icon("media-playback-start" if paused else "media-playback-pause"),
                            "Resume sync" if paused else "Pause sync",
                            lambda: self.summary.client.set_paused(not paused))
            for f in d["mirror"]["folders"]:
                if f["needs_force"]:
                    m.addAction(icon("dialog-warning"), f"Confirm deletions in \"{f['folder']}\"…",
                                lambda folder=f["folder"]: self.window.activity._force(folder))
        m.addSeparator()
        m.addAction(icon("nimbusdrive-offline"), "Offline folders…", lambda: self.window.show_tab(1))
        m.addAction(icon("configure"), "Settings…", lambda: self.window.show_tab(3))
        m.addSeparator()
        m.addAction(icon("application-exit"), "Hide icon", QApplication.quit)


def main(settings_only: bool = False) -> int:
    DBusQtMainLoop(set_as_default=True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("nimbus-drive")
    app.setApplicationDisplayName("Nimbus Drive")
    app.setDesktopFileName("io.github.nimbusdrive")
    app.setWindowIcon(icon("io.github.nimbusdrive"))
    summary = Summary()
    window = MainWindow(summary)
    tray = None
    if not settings_only and QSystemTrayIcon.isSystemTrayAvailable():
        bus = dbus.SessionBus()
        # One tray per session: a second `nimbus-drive tray` just opens the window.
        try:
            name = dbus.service.BusName("io.github.nimbusdrive.Tray", bus, do_not_queue=True)
        except dbus.exceptions.NameExistsException:
            settings_only = True
        else:
            app.tray_name = name
            tray = Tray(summary, window)
            window.has_tray = True
            tray.show()
            app.setQuitOnLastWindowClosed(False)
    if settings_only or tray is None or not summary.data.get("configured"):
        window.show_tab(2 if not summary.data.get("configured") else 0)
    return app.exec()

