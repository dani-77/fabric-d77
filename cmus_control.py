"""Shared cmus control helpers.

Used by dashboard.py (status polling + track/album controls) and
music_picker.py (starting playback of a picked album). Pulled out of
dashboard.py once a second module needed the same cmus-remote plumbing.
"""

import os
import subprocess
import time


def cmus_status() -> tuple[bool, str, str]:
    """Returns (running, status, track)."""
    try:
        result = subprocess.run(
            ["cmus-remote", "-Q"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        if result.returncode != 0:
            return False, "stopped", "—"
        status = "stopped"
        artist = title = ""
        for line in result.stdout.splitlines():
            if line.startswith("status "):
                status = line.split(" ", 1)[1].strip()
            elif line.startswith("tag artist "):
                artist = line.split(" ", 2)[2].strip()
            elif line.startswith("tag title "):
                title = line.split(" ", 2)[2].strip()
        track = f"{artist} — {title}" if artist and title else title or "—"
        if len(track) > 42:
            track = track[:40] + "…"
        return True, status, track
    except Exception:
        return False, "stopped", "—"


def cmus_current_album() -> tuple[str | None, str | None]:
    """Returns (status, album tag) of the current track, or (None, None) on failure."""
    result = subprocess.run(
        ["cmus-remote", "-Q"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    if result.returncode != 0:
        return None, None
    status = album = None
    for line in result.stdout.splitlines():
        if line.startswith("status "):
            status = line.split(" ", 1)[1].strip()
        elif line.startswith("tag album "):
            album = line.split(" ", 2)[2].strip()
    return status, album


def cmus_skip_album(direction: int, max_steps: int = 300):
    """Skips forward/backward by a whole album (direction=+1/-1).

    cmus has no native "next/previous album" command, so this steps track by
    track via cmus-remote until the "album" tag changes, relying on the
    library/queue being album-ordered (true when browsing a directory tree of
    many albums, which is the case this is meant for). Runs in a background
    thread since it may issue many cmus-remote calls in a row.
    """
    step_args = ["-n"] if direction > 0 else ["-r"]
    start_status, start_album = cmus_current_album()
    if start_status is None:
        return
    if start_album is None:
        # No album tag to key off — fall back to a plain track skip.
        subprocess.run(["cmus-remote"] + step_args,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    for _ in range(max_steps):
        subprocess.run(["cmus-remote"] + step_args,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status, album = cmus_current_album()
        if status is None or status == "stopped":
            return
        if album is not None and album != start_album:
            return


def start_cmus_headless():
    """Starts cmus in a detached tmux or screen session.

    Kills any existing "cmus" session first (even orphaned ones) and passes
    XDG_RUNTIME_DIR/HOME explicitly to cmus: a tmux server that survives a
    logout/compositor switch keeps the environment it was originally launched
    with, causing cmus to write its control socket to a path that the current
    cmus-remote can no longer find.
    """
    env_prefix = (
        f"XDG_RUNTIME_DIR={os.environ.get('XDG_RUNTIME_DIR', '')} "
        f"HOME={os.environ.get('HOME', '')} "
    )
    script = (
        "tmux kill-session -t cmus >/dev/null 2>&1; "
        f'command -v tmux >/dev/null 2>&1 && {{ tmux new-session -d -s cmus "{env_prefix}cmus"; exit 0; }}; '
        f'command -v screen >/dev/null 2>&1 && {{ screen -dmS cmus sh -c "{env_prefix}exec cmus"; exit 0; }}; '
        "exit 1"
    )
    subprocess.Popen(
        ["sh", "-c", script],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def cmus_play_album(album_dir: str):
    """Clears cmus's play queue and queues every track under album_dir.

    Uses the play queue (-q) rather than the playlist: -p alone just resumes
    whatever cmus's current view (Library, by default here) was already on,
    ignoring playlist changes entirely — verified by hand, it silently kept
    playing the previous album. The play queue always takes priority over
    the active view regardless of playback state, so this reliably jumps
    straight to the picked album.

    Starts cmus headless first if it isn't reachable yet, polling briefly for
    its control socket to come up. Intended to run off the GTK main thread —
    the wait loop can take a couple seconds.
    """
    running, _, _ = cmus_status()
    if not running:
        start_cmus_headless()
        for _ in range(20):
            time.sleep(0.25)
            running, _, _ = cmus_status()
            if running:
                break

    def run(*args):
        subprocess.run(["cmus-remote", *args],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run("-q", "-c")
    run("-q", album_dir)
    run("-n")
    run("-p")
