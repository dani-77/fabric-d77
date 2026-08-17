import os
import psutil
import re
import subprocess
from datetime import datetime

# gi._propertyhelper on Python 3.14 doesn't support IntEnum types (e.g.
# GtkLayerShell.Layer). Fall back to TYPE_PYOBJECT for unsupported types;
# the setters in WaylandWindow handle coercion themselves.
from gi._propertyhelper import Property as _GiProperty
from gi.repository import GObject as _GObject

_orig_type_from_python = _GiProperty._type_from_python
_orig_check_default = _GiProperty._check_default


def _patched_type_from_python(self, type_):
    try:
        return _orig_type_from_python(self, type_)
    except TypeError:
        return _GObject.TYPE_PYOBJECT


def _patched_check_default(self):
    if self.type == _GObject.TYPE_PYOBJECT:
        self.default = None
        return
    return _orig_check_default(self)


_GiProperty._type_from_python = _patched_type_from_python
_GiProperty._check_default = _patched_check_default

from fabric import Application, Fabricator
from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.eventbox import EventBox
from fabric.widgets.label import Label
from fabric.system_tray.widgets import SystemTray
from fabric.widgets.wayland import WaylandWindow as Window
from fabric.utils import get_relative_path

from dashboard import _launch_nmtui
from osd import get_power_profile


def _detect_compositor() -> str:
    """Return a compositor identifier based on environment variables."""
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if os.environ.get("SWAYSOCK"):
        return "sway"
    if os.environ.get("I3SOCK"):
        return "i3"
    if os.environ.get("NIRI_SOCKET"):
        return "niri"
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "hyprland" in desktop:
        return "hyprland"
    if "sway" in desktop:
        return "sway"
    if "niri" in desktop:
        return "niri"
    return "unknown"


def _create_workspaces_widget(**kwargs):
    """Return the right workspaces widget for the running compositor."""
    compositor = _detect_compositor()
    if compositor == "hyprland":
        from fabric.hyprland.widgets import HyprlandWorkspaces, WorkspaceButton
        return HyprlandWorkspaces(
            buttons_factory=lambda ws_id: WorkspaceButton(id=ws_id, label=None),
            **kwargs,
        )
    if compositor in ("sway", "i3"):
        from fabric.i3.widgets import I3Workspaces, WorkspaceButton
        return I3Workspaces(
            buttons_factory=lambda ws_id: WorkspaceButton(id=ws_id, label=None),
            **kwargs,
        )
    if compositor == "niri":
        from niri import NiriWorkspaces
        return NiriWorkspaces(**kwargs)
    # Unsupported compositor — caller should check for None and skip the widget.
    return None

AUDIO_WIDGET = True
if AUDIO_WIDGET is True:
    try:
        from fabric.audio.service import Audio
    except Exception as e:
        AUDIO_WIDGET = False
        print(e)


class VolumeWidget(Box):
    def __init__(self, osd=None, **kwargs):
        self.osd = osd
        self.icon = Image(icon_name="audio-speakers-symbolic", icon_size=14)
        self.label = Label(name="volume-label", label="0%")
        self.content = Box(spacing=4, orientation="h", children=[self.icon, self.label])
        self.audio = Audio(notify_speaker=self.on_speaker_changed)
        super().__init__(
            children=EventBox(
                events=["scroll", "button-press"],
                child=self.content,
                on_scroll_event=self.on_scroll,
                on_button_press_event=self.on_click,
            ),
            **kwargs,
        )

    def on_scroll(self, _, event):
        match event.direction:
            case 0:
                self.audio.speaker.volume += 5
            case 1:
                self.audio.speaker.volume -= 5
        return

    def on_click(self, *_):
        # Toggle mute via amixer/ALSA (same backend as the XF86AudioMute key)
        # so the OSD detects the change and shows itself.
        if self.osd is not None:
            self.osd.volume_mute_toggle()
        return

    def on_speaker_changed(self):
        if not self.audio.speaker:
            return
        self.label.set_label(f"{int(self.audio.speaker.volume)}%")
        self._update_icon()
        self.audio.speaker.connect("changed", lambda *_: self._update_icon())
        return self.audio.speaker.bind(
            "volume", "label", self.label, lambda _, v: f"{int(v)}%"
        )

    def _update_icon(self):
        speaker = self.audio.speaker
        if not speaker:
            return
        icon_name = "audio-volume-muted-symbolic" if speaker.muted else "audio-speakers-symbolic"
        self.icon.set_from_icon_name(icon_name, 14)


def get_wifi_details():
    try:
        net_root = "/sys/class/net"
        iface = next(
            (e for e in os.listdir(net_root)
             if os.path.isdir(os.path.join(net_root, e, "wireless"))),
            None,
        )
        if iface:
            output = subprocess.check_output(
                ["iw", "dev", iface, "link"],
                text=True, stderr=subprocess.DEVNULL,
            )
            ssid, percent = None, None
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("SSID:"):
                    ssid = line.split(":", 1)[1].strip()
                elif line.startswith("signal:"):
                    dbm = int(line.split()[1])
                    percent = max(0, min(100, 2 * (dbm + 100)))
            if ssid and percent is not None:
                if len(ssid) > 14:
                    ssid = ssid[:14] + "…"
                return "network-wireless-symbolic", f"{ssid} · {percent}%"
    except Exception:
        pass
    return "network-wireless-offline-symbolic", "Disconnected"


_UPOWER = "org.freedesktop.UPower"
_UPOWER_DISPLAY_DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"
_UPOWER_DEVICE_IF = "org.freedesktop.UPower.Device"

# org.freedesktop.UPower.Device's `State` enum.
_STATE_CHARGING, _STATE_DISCHARGING, _STATE_FULLY_CHARGED = 1, 2, 4


def _gdbus_get(dest, path, iface, prop):
    """Reads one D-Bus property via `gdbus`, returns its raw variant text
    (e.g. "(<uint32 2>,)", "(<true>,)") or "" on failure."""
    try:
        return subprocess.check_output(
            ["gdbus", "call", "--system", "--dest", dest, "--object-path", path,
             "--method", "org.freedesktop.DBus.Properties.Get", iface, prop],
            text=True, stderr=subprocess.DEVNULL, timeout=2,
        )
    except Exception:
        return ""


def _format_duration(seconds):
    """'Xh Ymin' (or just 'Ymin' under an hour) from a duration in seconds."""
    total_min = round(seconds / 60)
    h, m = divmod(total_min, 60)
    return f"{h}h {m}min" if h > 0 else f"{m}min"


def _profile_label(profile):
    """Mirrors Osd.qml's power-profile label mapping (quickshell-d77/utumno)."""
    return {
        "performance": "Performance",
        "power-saver": "Power saver",
        "balanced": "Balanced",
    }.get(profile, "Unknown")


def get_battery_info():
    """Reads UPower's DisplayDevice — aggregated across every battery, and
    the only way to tell "no battery" apart from "haven't polled yet" —
    instead of the first /sys/class/power_supply/*/type == Battery entry.
    Same fix applied to quickshell-d77's batProc and utumno/helium-d77's
    UPower-backed readers; also picks up TimeToEmpty/TimeToFull from
    UPower directly rather than the optional (not every driver exposes
    them) sysfs time_to_*_now attributes this used to read.

    Returns (icon_name, percent_text, tooltip_text, present).
    """
    def prop(name):
        return _gdbus_get(_UPOWER, _UPOWER_DISPLAY_DEVICE, _UPOWER_DEVICE_IF, name)

    try:
        kind = re.search(r"uint32 (\d+)", prop("Type"))
        present = "true" in prop("IsPresent")
        if not kind or kind.group(1) != "2" or not present:
            return "battery-missing-symbolic", "N/A", "", False

        pct_match = re.search(r"([\d.]+)", prop("Percentage"))
        percent = round(float(pct_match.group(1))) if pct_match else 0

        state_match = re.search(r"uint32 (\d+)", prop("State"))
        state = int(state_match.group(1)) if state_match else 0

        def secs(raw):
            m = re.search(r"int64 (\d+)", raw)
            return int(m.group(1)) if m else 0

        time_to_empty = secs(prop("TimeToEmpty"))
        time_to_full = secs(prop("TimeToFull"))

        if state == _STATE_CHARGING:
            icon = "battery-caution-charging-symbolic"
        elif percent > 25:
            icon = "battery-good-symbolic"
        else:
            icon = "battery-caution-symbolic"

        if state == _STATE_CHARGING and time_to_full > 0:
            time_line = f"Charging — {_format_duration(time_to_full)} until full"
        elif state == _STATE_CHARGING:
            time_line = "Charging"
        elif state == _STATE_DISCHARGING and time_to_empty > 0:
            time_line = f"{_format_duration(time_to_empty)} remaining"
        elif state == _STATE_DISCHARGING:
            time_line = "On battery"
        elif state == _STATE_FULLY_CHARGED:
            time_line = "Fully charged"
        else:
            time_line = "Battery state unknown"

        profile = _profile_label(get_power_profile())
        tooltip = f"{time_line}\nPower profile: {profile}"

        return icon, f"{percent}%", tooltip, True
    except Exception:
        pass
    return "battery-missing-symbolic", "N/A", "", False


class StatusBar(Window):
    def __init__(self, osd=None):
        self.osd = osd
        super().__init__(
            name="bar",
            layer="top",
            anchor="left top right",
            margin="10px 10px -2px 10px",
            exclusivity="auto",
            visible=False,
        )
        cpu_icon = Image(icon_name="cpu-symbolic", icon_size=14)
        cpu_label = Label(name="cpu-label", label="0%")
        cpu_box = Box(spacing=4, orientation="h", children=[cpu_icon, cpu_label])
        cpu_label.build(
            lambda lbl: Fabricator(
                interval=1000,
                poll_from=lambda f: psutil.cpu_percent(),
                on_changed=lambda _, value: lbl.set_label(f"{int(value)}%"),
            )
        )

        ram_icon = Image(icon_name="ram-symbolic", icon_size=14)
        ram_label = Label(name="ram-label", label="0%")
        ram_box = Box(spacing=4, orientation="h", children=[ram_icon, ram_label])
        ram_label.build(
            lambda lbl: Fabricator(
                interval=2000,
                poll_from=lambda f: psutil.virtual_memory().percent,
                on_changed=lambda _, value: lbl.set_label(f"{int(value)}%"),
            )
        )

        wifi_icon = Image(icon_name="network-wireless-symbolic", icon_size=14)
        wifi_label = Label(name="wifi-label", label="--")
        wifi_content = Box(spacing=4, orientation="h", children=[wifi_icon, wifi_label])
        wifi_box = EventBox(
            events="button-press",
            child=wifi_content,
            on_button_press_event=lambda *_: _launch_nmtui(),
        )
        def update_wifi(_, info):
            icon_name, text = info
            wifi_icon.set_from_icon_name(icon_name, 14)
            wifi_label.set_label(text)

        wifi_label.build(
            lambda lbl: Fabricator(
                interval=4000,
                poll_from=lambda f: get_wifi_details(),
                on_changed=update_wifi,
            )
        )

        battery_icon = Image(icon_name="battery-full-symbolic", icon_size=14)
        battery_label = Label(name="battery-label", label="--%")
        battery_content = Box(spacing=4, orientation="h", children=[battery_icon, battery_label])
        battery_box = EventBox(
            events="button-press",
            child=battery_content,
            on_button_press_event=lambda *_: self.osd.power_profile_cycle() if self.osd else None,
        )

        def update_battery(_, info):
            icon_name, percent_text, tooltip_text, present = info
            # Hidden on a battery-less desktop instead of showing the old
            # "N/A" placeholder forever — see get_battery_info().
            battery_box.set_visible(present)
            if not present:
                return
            battery_icon.set_from_icon_name(icon_name, 14)
            battery_label.set_label(percent_text)
            battery_box.set_tooltip_text(tooltip_text)

        battery_label.build(
            lambda lbl: Fabricator(
                interval=5000,
                poll_from=lambda f: get_battery_info(),
                on_changed=update_battery,
            )
        )

        clock_label = Label(name="date-time")
        clock_label.build(
            lambda lbl: Fabricator(
                interval=1000,
                poll_from=lambda f: datetime.now().strftime("%d/%m/%Y %H:%M"),
                on_changed=lambda _, value: lbl.set_label(value),
            )
        )

        self.system_status = Box(
            name="system-status",
            spacing=14,
            orientation="h",
            children=[
                cpu_box,
                ram_box,
                wifi_box,
                battery_box,
            ]
            + ([VolumeWidget(osd=self.osd)] if AUDIO_WIDGET else []),
        )

        _ws_widget = _create_workspaces_widget(name="workspaces", spacing=4)
        self.left_container = Box(
            name="start-container",
            children=[_ws_widget] if _ws_widget is not None else [],
        )

        spacer = Box()
        spacer.set_hexpand(True)

        self.right_container = Box(
            name="end-container",
            spacing=12,
            orientation="h",
            children=[
                #SystemTray(name="system-tray", spacing=4),
                self.system_status,
                clock_label,
            ],
        )

        self.main_layout = Box(
            name="bar-inner",
            orientation="h",
            spacing=0,
            children=[self.left_container, spacer, self.right_container],
        )

        self.children = self.main_layout
        return self.show_all()


if __name__ == "__main__":
    bar = StatusBar()
    app = Application("bar", bar)
    app.set_stylesheet_from_file(get_relative_path("./style.css"))
    app.run()
