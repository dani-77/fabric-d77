import os

from fabric.widgets.box import Box
from fabric.widgets.label import Label
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.wayland import WaylandWindow as Window


class SessionMenu(Window):
    """Power / session menu rendered as a layer-shell window centered on screen.

    On Wayland (Hyprland) a ``Gtk.Menu`` popup is an ``xdg_popup`` that must be
    anchored to a parent surface, so it cannot be freely positioned at the
    center of the screen. Using a layer-shell ``WaylandWindow`` with
    ``anchor="center"`` is the reliable way to center it (this mirrors how the
    application launcher is centered).
    """

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

        logout_cmd = "pkill -KILL -u $USER"
        if "HYPRLAND_INSTANCE_SIGNATURE" in os.environ:
            logout_cmd = "hyprctl dispatch 'hl.dsp.exit()'"

        self.add(
            Box(
                name="session-menu",
                orientation="v",
                spacing=4,
                children=[
                    self.bake_item(
                        "Lock", "system-lock-screen-symbolic", "hyprlock"
                    ),
                    self.bake_item(
                        "Log Out", "system-log-out-symbolic", logout_cmd
                    ),
                    self.bake_item(
                        "Reboot", "system-reboot-symbolic", "loginctl reboot"
                    ),
                    self.bake_item(
                        "Power Off", "system-shutdown-symbolic", "loginctl poweroff"
                    ),
                ],
            )
        )

        self.add_keybinding("escape", lambda *_: self.set_visible(False))
        self.show_all()

    def bake_item(self, label_text: str, icon_name: str, command: str) -> Button:
        return Button(
            child=Box(
                orientation="h",
                spacing=12,
                children=[
                    Image(icon_name=icon_name, icon_size=32),
                    Label(label=label_text, h_align="start"),
                ],
            ),
            on_clicked=lambda *_: (self.set_visible(False), os.system(command)),
        )

    def toggle(self):
        if self.get_visible():
            self.set_visible(False)
        else:
            self.show_all()
            self.set_visible(True)
