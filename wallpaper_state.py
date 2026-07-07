import os

# Onde o último wallpaper escolhido no picker (wallpaper_selector.py) é
# persistido, para sobreviver a logout/reboot. Lido no arranque do Hyprland
# por apply-saved-wallpaper.sh, antes do awww-daemon aplicar nada.
#
# Namespace próprio (~/.cache/fabric-d77/...), separado do usado pelo
# quickshell-d77 (~/.cache/quickshell/...) — são shells independentes e não
# devem pisar o estado uma da outra.
STATE_DIR = os.path.expanduser("~/.cache/fabric-d77/wallpaper")
STATE_FILE = os.path.join(STATE_DIR, "current")


def read_current() -> str | None:
    """Devolve o caminho guardado, ou None se não houver nenhum válido."""
    try:
        with open(STATE_FILE, "r") as f:
            path = f.read().strip()
    except FileNotFoundError:
        return None
    return path if path and os.path.isfile(path) else None


def write_current(path: str) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        f.write(path)


def clear_current() -> None:
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass
