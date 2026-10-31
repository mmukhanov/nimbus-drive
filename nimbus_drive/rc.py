"""Minimal client for the rclone remote-control API over a unix socket."""

import http.client
import json
import socket
from pathlib import Path


class RcError(Exception):
    pass


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: Path, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


class RcClient:
    def __init__(self, socket_path: Path, timeout: float = 10.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def available(self) -> bool:
        return self.socket_path.is_socket()

    def call(self, command: str, timeout: float | None = None, **params) -> dict:
        conn = _UnixConnection(self.socket_path, timeout or self.timeout)
        try:
            body = json.dumps(params)
            conn.request("POST", "/" + command, body, {"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = resp.read()
        except OSError as e:
            raise RcError(f"{command}: {e}") from e
        finally:
            conn.close()
        try:
            result = json.loads(data or b"{}")
        except ValueError as e:
            raise RcError(f"{command}: bad response") from e
        if resp.status != 200:
            raise RcError(f"{command}: {result.get('error', resp.status)}")
        return result
