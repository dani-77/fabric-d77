"""Info Dashboard — fabric-d77.

Overlay centrado com: nome de utilizador, OS, uptime e meteorologia local
(geolocalização por IP via wttr.in, sem API key).

Ativado por SIGRTMIN+7 em main.py com dashboard.toggle().
"""

import os
import threading
import urllib.request

import psutil

from gi.repository import GLib

from fabric.widgets.box import Box
from fabric.widgets.label import Label
from fabric.widgets.image import Image
from fabric.widgets.wayland import WaylandWindow as Window


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_username() -> str:
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        return os.getenv("USER", "unknown")


def _get_os_name() -> str:
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "Linux"


def _get_uptime() -> str:
    seconds = int(psutil.time.time() - psutil.boot_time())
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _fetch_weather_sync() -> str:
    """Bloqueia — deve ser chamado numa thread separada."""
    try:
        req = urllib.request.Request(
            "https://wttr.in/?format=3",
            headers={"User-Agent": "curl/7.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return "meteorologia indisponível"


# ── Widget ───────────────────────────────────────────────────────────────────

class InfoDashboard(Window):
    """Painel de informação rápida acionado por SIGRTMIN+7."""

    def __init__(self, **kwargs):
        super().__init__(
            layer="overlay",
            anchor="center",
            exclusivity="none",
            keyboard_mode="on-demand",
            visible=False,
            all_visible=False,
            **kwargs,
        )

        self._weather_label = Label(
            name="dashboard-weather",
            label="a carregar…",
            h_align="start",
        )

        def _row(icon_name: str, text: str, name: str) -> Box:
            return Box(
                name="dashboard-row",
                orientation="h",
                spacing=12,
                children=[
                    Image(icon_name=icon_name, icon_size=20),
                    Label(name=name, label=text, h_align="start"),
                ],
            )

        self._uptime_label = Label(
            name="dashboard-uptime",
            label=_get_uptime(),
            h_align="start",
        )
        uptime_row = Box(
            name="dashboard-row",
            orientation="h",
            spacing=12,
            children=[
                Image(icon_name="appointment-soon-symbolic", icon_size=20),
                self._uptime_label,
            ],
        )
        weather_row = Box(
            name="dashboard-row",
            orientation="h",
            spacing=12,
            children=[
                Image(icon_name="weather-few-clouds-symbolic", icon_size=20),
                self._weather_label,
            ],
        )

        self.add(
            Box(
                name="info-dashboard",
                orientation="v",
                spacing=10,
                children=[
                    _row(
                        "avatar-default-symbolic",
                        _get_username(),
                        "dashboard-user",
                    ),
                    _row(
                        "computer-symbolic",
                        _get_os_name(),
                        "dashboard-os",
                    ),
                    uptime_row,
                    weather_row,
                ],
            )
        )

        self.add_keybinding("escape", lambda *_: self.set_visible(False))
        self.show_all()

    # ── API pública ───────────────────────────────────────────────────────────

    def toggle(self):
        if self.get_visible():
            self.set_visible(False)
        else:
            self._uptime_label.set_label(_get_uptime())
            self._weather_label.set_label("a carregar…")
            self.show_all()
            self.set_visible(True)
            threading.Thread(target=self._load_weather, daemon=True).start()

    def _load_weather(self):
        result = _fetch_weather_sync()
        GLib.idle_add(self._weather_label.set_label, result)
