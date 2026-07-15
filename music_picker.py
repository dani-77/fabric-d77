"""Music Picker — fabric-d77.

Search popup to browse Artist/Album folders under MUSIC_DIR and start
playback of the picked album in cmus. Mirrors launcher.py's search+list
pattern (Entry + filtered ScrolledWindow), swapping desktop apps for album
folders and launch_app() for cmus_play_album().
Opened from the dashboard's "Browse albums" button (dashboard.py).
"""

import operator
import os
import threading
from collections.abc import Iterator

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.entry import Entry
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from fabric.widgets.wayland import WaylandWindow as Window
from fabric.utils import idle_add, remove_handler

from cmus_control import cmus_play_album

MUSIC_DIR = os.path.expanduser("~/Música")


class Album:
    __slots__ = ("artist", "title", "path")

    def __init__(self, artist: str, title: str, path: str):
        self.artist = artist
        self.title = title
        self.path = path


def _scan_albums(root: str) -> list[Album]:
    albums = []
    if not os.path.isdir(root):
        return albums
    for artist in sorted(os.listdir(root)):
        artist_dir = os.path.join(root, artist)
        if not os.path.isdir(artist_dir):
            continue
        for album in sorted(os.listdir(artist_dir)):
            album_dir = os.path.join(artist_dir, album)
            if os.path.isdir(album_dir):
                albums.append(Album(artist, album, album_dir))
    return albums


class MusicPicker(Window):
    def __init__(self, **kwargs):
        super().__init__(
            layer="top",
            anchor="center",
            exclusivity="none",
            keyboard_mode="on-demand",
            visible=False,
            all_visible=False,
            **kwargs,
        )
        self._arranger_handler: int = 0
        self._all_albums = _scan_albums(MUSIC_DIR)

        self.viewport = Box(spacing=2, orientation="v")
        self.search_entry = Entry(
            placeholder="Search Artist / Album...",
            h_expand=True,
            notify_text=lambda entry, *_: self.arrange_viewport(entry.get_text()),
        )
        self.scrolled_window = ScrolledWindow(
            min_content_size=(320, 360),
            max_content_size=(320 * 2, 360),
            child=self.viewport,
        )

        self.add(
            Box(
                name="launcher-window",
                spacing=2,
                orientation="v",
                style="margin: 2px",
                children=[
                    Box(
                        spacing=2,
                        orientation="h",
                        children=[
                            self.search_entry,
                            Button(
                                image=Image(icon_name="window-close"),
                                tooltip_text="Exit",
                                on_clicked=lambda *_: self.set_visible(False),
                            ),
                        ],
                    ),
                    self.scrolled_window,
                ],
            )
        )
        self.add_keybinding("escape", lambda *_: self.set_visible(False))
        self.show_all()

    def refresh_albums(self):
        self._all_albums = _scan_albums(MUSIC_DIR)
        self.search_entry.set_text("")
        self.arrange_viewport("")

    def arrange_viewport(self, query: str = ""):
        remove_handler(self._arranger_handler) if self._arranger_handler else None
        self.viewport.children = []

        filtered_iter = iter(
            [
                album
                for album in self._all_albums
                if query.casefold() in f"{album.artist} {album.title}".casefold()
            ]
        )
        should_resize = operator.length_hint(filtered_iter) == len(self._all_albums)

        self._arranger_handler = idle_add(
            lambda *args: self.add_next_album(*args)
            or (self.resize_viewport() if should_resize else False),
            filtered_iter,
            pin=True,
        )
        return False

    def add_next_album(self, albums_iter: Iterator[Album]):
        if not (album := next(albums_iter, None)):
            return False
        self.viewport.add(self.bake_album_slot(album))
        return True

    def resize_viewport(self):
        self.scrolled_window.set_min_content_width(
            self.viewport.get_allocation().width  # type: ignore
        )
        return False

    def bake_album_slot(self, album: Album, **kwargs) -> Button:
        return Button(
            child=Box(
                orientation="h",
                spacing=12,
                children=[
                    Image(icon_name="audio-x-generic-symbolic", h_align="start", icon_size=32),
                    Label(
                        label=f"{album.artist} — {album.title}",
                        v_align="center",
                        h_align="center",
                    ),
                ],
            ),
            tooltip_text=album.path,
            on_clicked=lambda *_: (
                threading.Thread(
                    target=cmus_play_album, args=(album.path,), daemon=True
                ).start(),
                self.set_visible(False),
            ),
            **kwargs,
        )

    def toggle(self):
        if self.get_visible():
            self.set_visible(False)
        else:
            self.show_all()
            self.refresh_albums()
            self.set_visible(True)
            self.search_entry.grab_focus()
