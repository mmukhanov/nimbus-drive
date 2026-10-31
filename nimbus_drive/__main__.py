"""Command line entry point: `nimbus-drive <command>`."""

import argparse
import sys

from . import __version__


def main() -> int:
    parser = argparse.ArgumentParser(prog="nimbus-drive",
                                     description="Google Drive для Linux на базе rclone")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("daemon", help="фоновый сервис (запускается через systemd)")
    sub.add_parser("tray", help="значок в трее")
    sub.add_parser("settings", help="окно настроек")
    sub.add_parser("status", help="состояние синхронизации")
    for name, help_ in (("download", "скачать файлы или папки на компьютер"),
                        ("free", "освободить место (оставить только в облаке)"),
                        ("offline", "всегда хранить папки офлайн"),
                        ("online", "перестать хранить папки офлайн")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("paths", nargs="+")
        if name == "online":
            p.add_argument("--trash-local", action="store_true",
                           help="переместить локальную копию в корзину")
    sub.add_parser("sync", help="синхронизировать офлайн-папки сейчас")
    args = parser.parse_args()

    if args.cmd == "daemon":
        from .daemon import main as daemon_main
        return daemon_main()
    if args.cmd in ("tray", "settings", None):
        from .gui import main as gui_main
        return gui_main(settings_only=args.cmd == "settings")

    import os
    from .client import DaemonClient
    client = DaemonClient()
    if not client.running():
        print("Сервис не запущен: systemctl --user start nimbus-drive", file=sys.stderr)
        return 1
    paths = [os.path.abspath(p) for p in getattr(args, "paths", [])]
    if args.cmd == "status":
        s = client.summary()
        m = s["mount"]
        print(f"Аккаунт: {s['remote'] or 'не подключён'}")
        print(f"Google Drive: {m['path']} — {'подключён' if m['ready'] else m['error'] or 'нет'}")
        print(f"Кэш: {s['cache']['bytes'] / 2**20:.0f} МБ из {s['cache']['max']}")
        for d in s["downloads"]:
            print(f"  ↓ {d['name']} {d['pct']}%")
        for u in s["uploads"]:
            print(f"  ↑ {u['name']} {u['pct']}%")
        for f in s["mirror"]["folders"]:
            state = "синхронизируется" if f["running"] else f["error"] or "ок"
            print(f"Офлайн: {f['folder']} → {f['local']} — {state}")
    elif args.cmd == "download":
        print(client.download(paths))
    elif args.cmd == "free":
        print(client.free_space(paths))
    elif args.cmd == "offline":
        print(client.set_offline(paths, True))
    elif args.cmd == "online":
        print(client.set_offline(paths, False, args.trash_local))
    elif args.cmd == "sync":
        client.sync_now()
    return 0


if __name__ == "__main__":
    sys.exit(main())
