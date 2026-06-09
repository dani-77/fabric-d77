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

from bar import StatusBar
from launcher import AppLauncher
from session_menu import SessionMenu

class MainStatusBar(StatusBar):
    def __init__(self, launcher_window: AppLauncher, session_menu: SessionMenu):
        self.launcher = launcher_window
        self.session_menu = session_menu
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
        # The session menu is a layer-shell window anchored to the center of the
        # screen (see session_menu.SessionMenu), so it always opens centered
        # regardless of where the power button lives on the bar.
        self.session_menu.toggle()

    def toggle_launcher(self):
        if self.launcher.get_visible():
            self.launcher.set_visible(False)
        else:
            self.launcher.show_all()
            self.launcher.refresh_apps()
            self.launcher.set_visible(True)
            self.launcher.search_entry.grab_focus()


if __name__ == "__main__":
    launcher = AppLauncher()
    launcher.set_visible(False)
    launcher.add_keybinding("escape", lambda: launcher.set_visible(False))

    session_menu = SessionMenu()
    session_menu.set_visible(False)

    bar = MainStatusBar(launcher_window=launcher, session_menu=session_menu)
    app = Application("d77-shell", [bar, launcher, session_menu])
    
    signal.signal(signal.SIGUSR1, lambda signum, frame: bar.toggle_launcher())
    signal.signal(signal.SIGUSR2, lambda signum, frame: bar.popup_power_menu())
    
    style_path = get_relative_path("./style.css")
    if os.path.exists(style_path):
        app.set_stylesheet_from_file(style_path)

    app.run()
