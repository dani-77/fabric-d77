import os
import sys
import signal

if "HYPRLAND_INSTANCE_SIGNATURE" not in os.environ:
    from unittest.mock import MagicMock
    from fabric.widgets.box import Box
    mock_module = MagicMock()
    mock_module.Hyprland = MagicMock
    mock_module.HyprlandWorkspaces = lambda **kwargs: Box(name="workspaces-placeholder")
    mock_module.WorkspaceButton = lambda **kwargs: Box()
    sys.modules["fabric.hyprland.widgets"] = mock_module
    sys.modules["fabric.hyprland.service"] = mock_module

from fabric import Application
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.utils import get_relative_path

from gi.repository import Gtk

from bar import StatusBar
from launcher import AppLauncher

class MainStatusBar(StatusBar):
    def __init__(self, launcher_window: AppLauncher):
        self.launcher = launcher_window
        super().__init__()

    def show_all(self):
        launcher_button = Button(
            name="launcher-button",
            child=Image(icon_name="view-app-grid-symbolic", icon_size=14),
            on_clicked=lambda *_: self.toggle_launcher(),
        )

        if hasattr(self, "main_layout") and len(self.main_layout.children) > 0:
            left_container = self.main_layout.children[0]
            current_left = left_container.children
            current_left.insert(0, launcher_button)
            left_container.children = current_left

        self.power_button = Button(
            name="power-button",
            child=Image(icon_name="system-shutdown-symbolic", icon_size=14),
            on_clicked=lambda btn: self.popup_power_menu(btn),
        )

        if hasattr(self, "main_layout") and len(self.main_layout.children) > 2:
            right_container = self.main_layout.children[2]
            right_container.add(self.power_button)

        return super().show_all()

    def popup_power_menu(self, button=None):
        target_widget = button if button else getattr(self, "power_button", None)
        if not target_widget:
            return

        menu = Gtk.Menu()
        menu.set_name("session-menu")

        def create_item(label_text, icon_name, command):
            item = Gtk.MenuItem()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
            label = Gtk.Label(label=label_text)
            box.pack_start(icon, False, False, 0)
            box.pack_start(label, False, False, 0)
            item.add(box)
            item.connect("activate", lambda _: os.system(command))
            return item

        logout_cmd = "pkill -KILL -u $USER"
        if "HYPRLAND_INSTANCE_SIGNATURE" in os.environ:
            logout_cmd = "hyprctl dispatch exit"
        
        menu.append(create_item("Log Out", "system-log-out-symbolic", logout_cmd))
        menu.append(create_item("Reboot", "system-reboot-symbolic", "loginctl reboot"))
        menu.append(create_item("Power Off", "system-shutdown-symbolic", "loginctl poweroff"))

        menu.show_all()
        menu.popup_at_widget(target_widget, Gdk.Gravity.SOUTH, Gdk.Gravity.NORTH, None)

    def toggle_launcher(self):
        if self.launcher.get_visible():
            self.launcher.set_visible(False)
        else:
            self.launcher.show_all()
            self.launcher.refresh_apps()
            self.launcher.set_visible(True)
            self.launcher.search_entry.grab_focus()


if __name__ == "__main__":
    from gi.repository import Gdk
    
    launcher = AppLauncher()
    launcher.set_visible(False)
    launcher.add_keybinding("escape", lambda: launcher.set_visible(False))
    
    bar = MainStatusBar(launcher_window=launcher)
    app = Application("d77-shell", [bar, launcher])
    
    signal.signal(signal.SIGUSR1, lambda signum, frame: bar.toggle_launcher())
    signal.signal(signal.SIGUSR2, lambda signum, frame: bar.popup_power_menu())
    
    style_path = get_relative_path("./style.css")
    if os.path.exists(style_path):
        app.set_stylesheet_from_file(style_path)

    app.run()
