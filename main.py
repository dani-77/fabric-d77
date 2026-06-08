#!/usr/bin/env python3
import os
import sys
import signal

if "HYPRLAND_INSTANCE_SIGNATURE" not in os.environ:
    from unittest.mock import MagicMock
    
    mock_module = MagicMock()
    
    from fabric.widgets.box import Box
    mock_module.Hyprland = MagicMock
    mock_module.HyprlandWorkspaces = lambda **kwargs: Box(name="workspaces-placeholder")
    mock_module.WorkspaceButton = lambda **kwargs: Box()
    
    sys.modules["fabric.hyprland.widgets"] = mock_module
    sys.modules["fabric.hyprland.service"] = mock_module
    
    print("[Aviso] Socket do Hyprland não detetado. A emular ambiente para MangoWC...")

from fabric import Application
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.utils import get_relative_path

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
            current_children = left_container.children
            current_children.insert(0, launcher_button)
            left_container.children = current_children

        return super().show_all()

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
    
    bar = MainStatusBar(launcher_window=launcher)
    app = Application("desktop-shell", [bar, launcher])
    
    signal.signal(signal.SIGUSR1, lambda signum, frame: bar.toggle_launcher())
    
    style_path = get_relative_path("./style.css")
    if os.path.exists(style_path):
        app.set_stylesheet_from_file(style_path)

    app.run()
