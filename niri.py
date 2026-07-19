"""Niri IPC support: a workspaces widget for the niri compositor.

Fabric ships workspace widgets for Hyprland and sway/i3 but not niri, which
has no dedicated module upstream. Niri speaks its own line-delimited JSON
protocol over `$NIRI_SOCKET` (see `niri msg --help`): one JSON object per
line in, one JSON object per line back. A second connection can request
`{"EventStream":null}` to switch into a push mode that streams JSON events
(`WorkspacesChanged`, `WorkspaceActivated`, ...) instead of replying once.
"""

import os
import json
import socket
from loguru import logger

from fabric.core.service import Service, Signal
from fabric.core.widgets import WorkspaceButton, Workspaces
from fabric.utils.helpers import idle_add
from gi.repository import GLib


class Niri(Service):
    """A connection to niri's IPC socket, for commands and live events."""

    @Signal
    def workspaces_changed(self, workspaces: object): ...

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.socket_path = os.environ.get("NIRI_SOCKET")
        if self.socket_path:
            GLib.Thread.new("niri-event-stream", self._event_stream_task, None)

    def send_request(self, payload: dict):
        """Send one JSON request and return its `Ok` payload, or None on failure."""
        if not self.socket_path:
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(self.socket_path)
                sock.sendall((json.dumps(payload) + "\n").encode())
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
        except OSError as e:
            logger.warning(f"[Niri] request {payload} failed: {e}")
            return None

        try:
            reply = json.loads(buf.decode())
        except json.JSONDecodeError:
            return None

        ok = reply.get("Ok") if isinstance(reply, dict) else None
        if isinstance(ok, dict) and len(ok) == 1:
            return next(iter(ok.values()))
        return ok

    def get_workspaces(self) -> list[dict]:
        return self.send_request({"Workspaces": None}) or []

    def _event_stream_task(self, _):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.socket_path)
            sock.sendall(b'{"EventStream":null}\n')
        except OSError as e:
            logger.warning(f"[Niri] couldn't open event stream: {e}")
            return False

        buf = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    idle_add(self._handle_event_line, line)

        logger.warning("[Niri] event stream ended")
        return False

    def _handle_event_line(self, line: bytes):
        try:
            event = json.loads(line.decode())
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return

        if "WorkspacesChanged" in event:
            # the event already carries the full workspace list, no IPC needed
            workspaces = event["WorkspacesChanged"].get("workspaces", [])
            self.workspaces_changed(workspaces)
        elif "WorkspaceActivated" in event or "WorkspaceActiveWindowChanged" in event:
            # these events only carry a delta (id, focused window...); the
            # full list is cheap to re-fetch over the local socket
            self.workspaces_changed(self.get_workspaces())


connection: Niri | None = None


def get_niri_connection() -> Niri:
    global connection
    if not connection:
        connection = Niri()
    return connection


class NiriWorkspaces(Workspaces):
    def __init__(
        self,
        buttons=None,
        buttons_factory=lambda ws_id: WorkspaceButton(id=ws_id, label=None),
        invert_scroll: bool = False,
        **kwargs,
    ):
        super().__init__(buttons, buttons_factory, invert_scroll, **kwargs)
        self.connection = get_niri_connection()
        self.connection.connect("workspaces-changed", self.on_workspaces_changed)
        self.on_workspaces_changed(self.connection, self.connection.get_workspaces())

    def on_workspaces_changed(self, _, workspaces: list[dict]):
        # niri assigns workspaces a dynamic, monitor-local `idx` (already
        # 1-based, matching niri's own workspace-switch keybind numbering);
        # there's no fixed 1-9 grid like Hyprland/sway, so only workspaces
        # that actually exist get a button.
        by_id: dict[int, dict] = {}
        active_id = None
        for w in sorted(workspaces, key=lambda w: w.get("idx", 0)):
            wid = w.get("idx", 0)
            by_id[wid] = w
            if w.get("is_focused"):
                active_id = wid

        for wid in list(self._buttons.keys()):
            if wid not in by_id:
                self.workspace_destroyed(wid)

        for wid in sorted(by_id.keys()):
            if wid not in self._buttons:
                # workspace_created() re-inserts into the container even for
                # buttons already present (it only special-cases presets), so
                # only call it for genuinely new ids to avoid duplicate adds
                self.workspace_created(wid)
            self._buttons[wid].empty = by_id[wid].get("active_window_id") is None

        if active_id is not None:
            self.workspace_activated(active_id)

    def do_action_next(self):
        return self.connection.send_request({"Action": {"FocusWorkspaceDown": None}})

    def do_action_previous(self):
        return self.connection.send_request({"Action": {"FocusWorkspaceUp": None}})

    def do_button_clicked(self, button: WorkspaceButton):
        return self.connection.send_request(
            {"Action": {"FocusWorkspace": {"reference": {"Index": button.id}}}}
        )


__all__ = ["Niri", "NiriWorkspaces", "get_niri_connection"]
