import os
import psutil 
import subprocess
from datetime import datetime
from fabric import Application, Fabricator
from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.eventbox import EventBox
from fabric.widgets.label import Label
from fabric.system_tray.widgets import SystemTray
from fabric.widgets.wayland import WaylandWindow as Window
from fabric.hyprland.widgets import (
    Hyprland,
    HyprlandWorkspaces,
    WorkspaceButton,
)
from fabric.utils import get_relative_path

AUDIO_WIDGET = True

if AUDIO_WIDGET is True:
    try:
        from fabric.audio.service import Audio
    except Exception as e:
        AUDIO_WIDGET = False
        print(e)


class VolumeWidget(Box):
    def __init__(self, **kwargs):
        self.icon = Image(icon_name="audio-speakers-symbolic", icon_size=14)
        self.label = Label(name="volume-label", label="0%")
        self.content = Box(spacing=4, orientation="h", children=[self.icon, self.label])

        self.audio = Audio(notify_speaker=self.on_speaker_changed)

        super().__init__(
            children=EventBox(
                events="scroll", child=self.content, on_scroll_event=self.on_scroll
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

    def on_speaker_changed(self):
        if not self.audio.speaker:
            return

        self.label.set_label(f"{int(self.audio.speaker.volume)}%")
        return self.audio.speaker.bind(
            "volume", "label", self.label, lambda _, v: f"{int(v)}%"
        )


def get_wifi_details():
    try:
        cmd = "nmcli -t -f ACTIVE,SIGNAL device wifi list"
        output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        
        for line in output.strip().split("\n"):
            if line.startswith("sim:"):
                parts = line.split(":")
                if len(parts) >= 2:
                    signal = parts[1]
                    return f"{signal}%"
    except Exception:
        pass
    
    return "Disconnected"


def get_battery_info():
    try:
        bat_dir = "/sys/class/power_supply/BAT0"
        if not os.path.exists(bat_dir):
            bat_dir = "/sys/class/power_supply/BAT1"
            
        if os.path.exists(bat_dir):
            # 1. Ler a percentagem
            with open(f"{bat_dir}/capacity", "r") as f:
                percent = int(f.read().strip())
            
            with open(f"{bat_dir}/status", "r") as f:
                status = f.read().strip().lower()
            
            charging = status == "charging"
            time_str = ""
            
            time_file = f"{bat_dir}/time_to_full_now" if charging else f"{bat_dir}/time_to_empty_now"
            
            if os.path.exists(time_file):
                with open(time_file, "r") as f:
                    seconds = int(f.read().strip())
                
                if 0 < seconds < 1000000:
                    hours = seconds // 3600
                    minutes = (seconds % 3600) // 60
                    # Formata o tempo como (1h 45m)
                    time_str = f" ({hours}h {minutes}m)"
            
            if charging:
                icon = "battery-charging-symbolic"
            else:
                if percent > 25: icon = "battery-good-symbolic"
                else: icon = "battery-caution-symbolic"
                
            return icon, f"{percent}%{time_str}"
            
    except Exception:
        pass
        
    return "battery-missing-symbolic", "N/A"


class StatusBar(Window):
    def __init__(self):
        super().__init__(
            name="bar",
            layer="top",
            anchor="left top right",
            margin="10px 10px -2px 10px",
            exclusivity="auto",
            visible=False,
        )

        self.hyprland = Hyprland()

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
        wifi_box = Box(spacing=4, orientation="h", children=[wifi_icon, wifi_label])
        wifi_label.build(
            lambda lbl: Fabricator(
                interval=4000,
                poll_from=lambda f: get_wifi_details(),
                on_changed=lambda _, value: lbl.set_label(value),
            )
        )

        battery_icon = Image(icon_name="battery-full-symbolic", icon_size=14)
        battery_label = Label(name="battery-label", label="--%")
        battery_box = Box(spacing=4, orientation="h", children=[battery_icon, battery_label])
        
        def update_battery(_, info):
            icon_name, percent_text = info
            battery_icon.set_from_icon_name(icon_name, 14)
            battery_label.set_label(percent_text)

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
            + ([VolumeWidget()] if AUDIO_WIDGET else []),
        )

        def create_workspace_button(ws_id):
            btn = WorkspaceButton(id=ws_id, label=None)
            btn.connect("clicked", lambda _: self.hyprland.send_command(f"dispatch workspace {ws_id}"))
            return btn

        left_container = Box(
            name="start-container",
            children=HyprlandWorkspaces(
                name="workspaces",
                spacing=4,
                buttons_factory=create_workspace_button, 
            ),
        )

        spacer = Box()
        spacer.set_hexpand(True)

        right_container = Box(
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
            children=[left_container, spacer, right_container]
        )

        self.children = self.main_layout
        return self.show_all()


if __name__ == "__main__":
    bar = StatusBar()
    app = Application("bar", bar)
    app.set_stylesheet_from_file(get_relative_path("./style.css"))

    app.run()
