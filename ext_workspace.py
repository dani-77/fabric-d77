"""ext-workspace-v1 support: a workspaces widget for any compositor exposing it.

Fabric has no client for this protocol and python3-pywayland is no longer
packaged on Void, so this speaks the Wayland wire format directly over its own
connection. It only needs a handful of messages and none of them pass file
descriptors, so the standard library is enough:

    header: u32 object id, u32 (message size << 16 | opcode)
    args:   u32 for int/uint/object/new_id; for string/array, a u32 byte length
            (a string's includes its NUL) and the data padded to 4 bytes

Message opcodes below follow declaration order in wayland.xml and
ext-workspace-v1.xml.
"""

import os
import select
import socket
import struct
import time
from loguru import logger

from fabric.core.service import Service, Signal
from fabric.core.widgets import WorkspaceButton, Workspaces
from gi.repository import Gdk, GLib

WL_DISPLAY_ID = 1
WL_DISPLAY_SYNC = 0
WL_DISPLAY_GET_REGISTRY = 1
WL_DISPLAY_EVENT_ERROR = 0

WL_REGISTRY_BIND = 0
WL_REGISTRY_EVENT_GLOBAL = 0
WL_REGISTRY_EVENT_GLOBAL_REMOVE = 1

MANAGER_INTERFACE = "ext_workspace_manager_v1"
MANAGER_COMMIT = 0
MANAGER_EVENT_GROUP = 0
MANAGER_EVENT_WORKSPACE = 1
MANAGER_EVENT_DONE = 2
MANAGER_EVENT_FINISHED = 3

GROUP_DESTROY = 1
GROUP_EVENT_OUTPUT_ENTER = 1
GROUP_EVENT_OUTPUT_LEAVE = 2
GROUP_EVENT_WORKSPACE_ENTER = 3
GROUP_EVENT_WORKSPACE_LEAVE = 4
GROUP_EVENT_REMOVED = 5

WORKSPACE_DESTROY = 0
WORKSPACE_ACTIVATE = 1
WORKSPACE_EVENT_NAME = 1
WORKSPACE_EVENT_COORDINATES = 2
WORKSPACE_EVENT_STATE = 3
WORKSPACE_EVENT_CAPABILITIES = 4
WORKSPACE_EVENT_REMOVED = 5

STATE_ACTIVE = 1
STATE_URGENT = 2
STATE_HIDDEN = 4
CAPABILITY_ACTIVATE = 1

ROUNDTRIP_TIMEOUT = 1.0


def _encode_string(value: str) -> bytes:
    data = value.encode() + b"\0"
    return struct.pack("=I", len(data)) + data + b"\0" * (-len(data) % 4)


def _read_bytes(payload: bytes, offset: int = 0) -> tuple[bytes, int]:
    """Return one string/array argument and the offset just past its padding."""
    (size,) = struct.unpack_from("=I", payload, offset)
    start = offset + 4
    return payload[start : start + size], start + size + (-size % 4)


def _read_string(payload: bytes, offset: int = 0) -> tuple[str, int]:
    data, offset = _read_bytes(payload, offset)
    return data.rstrip(b"\0").decode(errors="replace"), offset


class WorkspaceHandle:
    def __init__(self, object_id: int):
        self.object_id = object_id
        self.name = ""
        self.coordinates: tuple[int, ...] = ()
        self.state = 0
        self.capabilities = 0

    @property
    def active(self) -> bool:
        return bool(self.state & STATE_ACTIVE)

    @property
    def urgent(self) -> bool:
        return bool(self.state & STATE_URGENT)

    @property
    def hidden(self) -> bool:
        return bool(self.state & STATE_HIDDEN)

    @property
    def can_activate(self) -> bool:
        return bool(self.capabilities & CAPABILITY_ACTIVATE)


class WorkspaceGroup:
    def __init__(self, object_id: int):
        self.object_id = object_id
        self.outputs: set[int] = set()
        self.workspaces: set[int] = set()


class ExtWorkspace(Service):
    """A Wayland connection tracking the compositor's workspace groups."""

    @Signal
    def workspaces_changed(self): ...

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.available = False
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._next_id = WL_DISPLAY_ID + 1
        self._registry_id = 0
        self._manager_id = 0
        self._sync_id = 0
        self._globals: dict[int, tuple[str, int]] = {}
        # wl_output objects by global name, in advertisement order. GDK keeps
        # its monitors in that same order, which is what ties a bar's monitor
        # to the outputs named by a workspace group.
        self._outputs: dict[int, int] = {}
        self.groups: dict[int, WorkspaceGroup] = {}
        self.workspaces: dict[int, WorkspaceHandle] = {}
        self._connect()

    def _connect(self):
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
        display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        path = display if os.path.isabs(display) else os.path.join(runtime_dir, display)
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(path)

            self._registry_id = self._new_id()
            self._send(
                WL_DISPLAY_ID, WL_DISPLAY_GET_REGISTRY, struct.pack("=I", self._registry_id)
            )
            self._roundtrip()

            manager = next(
                (
                    (name, version)
                    for name, (interface, version) in self._globals.items()
                    if interface == MANAGER_INTERFACE
                ),
                None,
            )
            if manager is None:
                self._close()
                return

            # Bind the outputs first, so the group's output_enter events have
            # objects to refer to.
            for name, (interface, _) in list(self._globals.items()):
                if interface == "wl_output":
                    self._bind_output(name)
            self._manager_id = self._bind(manager[0], MANAGER_INTERFACE, 1)
            self._roundtrip()
        except (OSError, TimeoutError) as e:
            logger.warning(f"[ExtWorkspace] couldn't connect to {path}: {e}")
            self._close()
            return

        self.available = True
        GLib.io_add_watch(
            self._sock.fileno(),
            GLib.PRIORITY_DEFAULT,
            GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
            self._on_socket_ready,
        )

    def _close(self):
        self.available = False
        if self._sock:
            self._sock.close()
            self._sock = None

    def _new_id(self) -> int:
        object_id = self._next_id
        self._next_id += 1
        return object_id

    def _send(self, object_id: int, opcode: int, args: bytes = b""):
        if self._sock:
            header = struct.pack("=II", object_id, (8 + len(args)) << 16 | opcode)
            self._sock.sendall(header + args)

    def _bind(self, name: int, interface: str, version: int) -> int:
        object_id = self._new_id()
        args = (
            struct.pack("=I", name)
            + _encode_string(interface)
            + struct.pack("=II", version, object_id)
        )
        self._send(self._registry_id, WL_REGISTRY_BIND, args)
        return object_id

    def _bind_output(self, name: int):
        self._outputs[name] = self._bind(name, "wl_output", 1)

    def _roundtrip(self):
        self._sync_id = self._new_id()
        self._send(WL_DISPLAY_ID, WL_DISPLAY_SYNC, struct.pack("=I", self._sync_id))
        deadline = time.monotonic() + ROUNDTRIP_TIMEOUT
        while self._sync_id:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self._sock], [], [], remaining)[0]:
                raise TimeoutError("no reply from the compositor")
            data = self._sock.recv(65536)
            if not data:
                raise OSError("connection closed")
            self._feed(data)

    def _on_socket_ready(self, _source, condition):
        try:
            data = self._sock.recv(65536, socket.MSG_DONTWAIT) if self._sock else b""
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data:
            logger.warning("[ExtWorkspace] connection to the compositor ended")
            self._close()
            return False
        self._feed(data)
        return self._sock is not None

    def _feed(self, data: bytes):
        self._buffer += data
        while len(self._buffer) >= 8:
            object_id, word = struct.unpack_from("=II", self._buffer)
            size = word >> 16
            if size < 8:
                logger.warning("[ExtWorkspace] malformed message, disconnecting")
                self._close()
                return
            if len(self._buffer) < size:
                return
            payload = self._buffer[8:size]
            self._buffer = self._buffer[size:]
            self._dispatch(object_id, word & 0xFFFF, payload)

    def _dispatch(self, object_id: int, opcode: int, payload: bytes):
        if object_id == WL_DISPLAY_ID:
            if opcode == WL_DISPLAY_EVENT_ERROR:
                message, _ = _read_string(payload, 8)
                logger.warning(f"[ExtWorkspace] protocol error: {message}")
                self._close()
        elif object_id == self._sync_id:
            self._sync_id = 0
        elif object_id == self._registry_id:
            self._handle_registry(opcode, payload)
        elif object_id == self._manager_id:
            self._handle_manager(opcode, payload)
        elif object_id in self.groups:
            self._handle_group(self.groups[object_id], opcode, payload)
        elif object_id in self.workspaces:
            self._handle_workspace(self.workspaces[object_id], opcode, payload)

    def _handle_registry(self, opcode: int, payload: bytes):
        if opcode == WL_REGISTRY_EVENT_GLOBAL:
            (name,) = struct.unpack_from("=I", payload)
            interface, offset = _read_string(payload, 4)
            (version,) = struct.unpack_from("=I", payload, offset)
            self._globals[name] = (interface, version)
            # A monitor plugged in after startup; the ones already there are
            # bound by _connect(), before the manager.
            if interface == "wl_output" and self._manager_id:
                self._bind_output(name)
        elif opcode == WL_REGISTRY_EVENT_GLOBAL_REMOVE:
            (name,) = struct.unpack_from("=I", payload)
            self._globals.pop(name, None)
            self._outputs.pop(name, None)

    def _handle_manager(self, opcode: int, payload: bytes):
        if opcode == MANAGER_EVENT_GROUP:
            (object_id,) = struct.unpack_from("=I", payload)
            self.groups[object_id] = WorkspaceGroup(object_id)
        elif opcode == MANAGER_EVENT_WORKSPACE:
            (object_id,) = struct.unpack_from("=I", payload)
            self.workspaces[object_id] = WorkspaceHandle(object_id)
        elif opcode == MANAGER_EVENT_DONE:
            self.workspaces_changed()
        elif opcode == MANAGER_EVENT_FINISHED:
            self._manager_id = 0
            self.groups.clear()
            self.workspaces.clear()
            self.workspaces_changed()

    def _handle_group(self, group: WorkspaceGroup, opcode: int, payload: bytes):
        if opcode == GROUP_EVENT_REMOVED:
            self._send(group.object_id, GROUP_DESTROY)
            del self.groups[group.object_id]
            return
        (target,) = struct.unpack_from("=I", payload)
        if opcode == GROUP_EVENT_OUTPUT_ENTER:
            group.outputs.add(target)
        elif opcode == GROUP_EVENT_OUTPUT_LEAVE:
            group.outputs.discard(target)
        elif opcode == GROUP_EVENT_WORKSPACE_ENTER:
            group.workspaces.add(target)
        elif opcode == GROUP_EVENT_WORKSPACE_LEAVE:
            group.workspaces.discard(target)

    def _handle_workspace(self, workspace: WorkspaceHandle, opcode: int, payload: bytes):
        if opcode == WORKSPACE_EVENT_NAME:
            workspace.name, _ = _read_string(payload)
        elif opcode == WORKSPACE_EVENT_COORDINATES:
            data, _ = _read_bytes(payload)
            workspace.coordinates = struct.unpack(f"={len(data) // 4}I", data)
        elif opcode == WORKSPACE_EVENT_STATE:
            (workspace.state,) = struct.unpack_from("=I", payload)
        elif opcode == WORKSPACE_EVENT_CAPABILITIES:
            (workspace.capabilities,) = struct.unpack_from("=I", payload)
        elif opcode == WORKSPACE_EVENT_REMOVED:
            self._send(workspace.object_id, WORKSPACE_DESTROY)
            del self.workspaces[workspace.object_id]

    def workspaces_for_monitor(self, monitor_index: int | None) -> list[WorkspaceHandle]:
        """Return the visible workspaces to show for a monitor, in display order."""
        outputs = list(self._outputs.values())
        output = None
        if monitor_index is not None and 0 <= monitor_index < len(outputs):
            output = outputs[monitor_index]

        groups = list(self.groups.values())
        # Compositors with one group per monitor (wasp) would otherwise repeat
        # every workspace, so never show more than one group. Without a match,
        # use the first one rather than an empty bar.
        group = next((g for g in groups if output in g.outputs), None)
        if group is None and groups:
            group = groups[0]
        if group is None:
            return []

        handles = (self.workspaces.get(object_id) for object_id in group.workspaces)
        visible = [w for w in handles if w is not None and not w.hidden]
        return sorted(visible, key=lambda w: (w.coordinates, w.object_id))

    def activate(self, workspace: WorkspaceHandle):
        self._send(workspace.object_id, WORKSPACE_ACTIVATE)
        self._send(self._manager_id, MANAGER_COMMIT)


connection: ExtWorkspace | None = None


def get_ext_workspace_connection() -> ExtWorkspace:
    global connection
    if not connection:
        connection = ExtWorkspace()
    return connection


class ExtWorkspaces(Workspaces):
    # GTK may need a moment to report which monitor a new layer surface is on.
    MONITOR_RETRIES = 20
    MONITOR_RETRY_MS = 100

    def __init__(
        self,
        buttons=None,
        buttons_factory=lambda ws_id: WorkspaceButton(id=ws_id, label=None),
        invert_scroll: bool = False,
        **kwargs,
    ):
        super().__init__(buttons, buttons_factory, invert_scroll, **kwargs)
        self.connection = get_ext_workspace_connection()
        # Button ids are positions in the list, which is also what
        # Workspaces.reorder_buttons() expects. Protocol object ids wouldn't work.
        self._shown: list[WorkspaceHandle] = []
        self._monitor_retries = 0
        self.connection.connect("workspaces-changed", lambda *_: self.refresh())
        self.connect("map", lambda *_: self._wait_for_monitor())
        display = Gdk.Display.get_default()
        if display is not None:
            display.connect("monitor-added", lambda *_: self.refresh())
            display.connect("monitor-removed", lambda *_: self.refresh())
        self.refresh()

    def _monitor_index(self) -> int | None:
        gdk_window = self.get_toplevel().get_window()
        display = Gdk.Display.get_default()
        # Compare with None: a Gdk.Display can evaluate as false in Python.
        if gdk_window is None or display is None:
            return None
        monitor = display.get_monitor_at_window(gdk_window)
        for i in range(display.get_n_monitors()):
            if display.get_monitor(i) == monitor:
                return i
        return None

    def _wait_for_monitor(self):
        self.refresh()
        self._monitor_retries = self.MONITOR_RETRIES
        GLib.timeout_add(self.MONITOR_RETRY_MS, self._retry_monitor)

    def _retry_monitor(self):
        self.refresh()
        self._monitor_retries -= 1
        return self._monitor_retries > 0

    def refresh(self):
        self._shown = self.connection.workspaces_for_monitor(self._monitor_index())

        for position in list(self._buttons.keys()):
            if position > len(self._shown):
                self.workspace_destroyed(position)

        for position, workspace in enumerate(self._shown, start=1):
            if position not in self._buttons:
                self.workspace_created(position)
            button = self._buttons[position]
            button.set_tooltip_text(workspace.name)
            if button.active != workspace.active:
                button.active = workspace.active
            if button.urgent != workspace.urgent:
                button.urgent = workspace.urgent

    def _activate_relative(self, step: int):
        active = next((i for i, w in enumerate(self._shown) if w.active), None)
        if active is None:
            return
        target = active + step
        if 0 <= target < len(self._shown) and self._shown[target].can_activate:
            self.connection.activate(self._shown[target])

    def do_action_next(self):
        self._activate_relative(1)

    def do_action_previous(self):
        self._activate_relative(-1)

    def do_button_clicked(self, button: WorkspaceButton):
        if 0 < button.id <= len(self._shown):
            workspace = self._shown[button.id - 1]
            if workspace.can_activate:
                self.connection.activate(workspace)


__all__ = ["ExtWorkspace", "ExtWorkspaces", "get_ext_workspace_connection"]
