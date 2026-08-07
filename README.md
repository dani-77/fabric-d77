# fabric-d77

A simple, good-looking desktop shell (top bar, launcher, lock screen, OSD,
Ollama chat, wallpaper picker) for Wayland compositors like Hyprland and
sway — built with [Fabric](https://github.com/Fabric-Development/fabric) and
Python.

<img src="doc/assets/fabric-d77-logo.png" alt="fabric-d77 logo" width="160">


> 👉 Looking for the full technical/developer documentation (architecture,
> packaging internals, PAM/session-lock details, etc.)? See
> [`doc/README.md`](doc/README.md).

## What is this?

fabric-d77 is a lightweight desktop shell that adds the bits a bare Wayland
compositor doesn't give you out of the box:

- A **top bar** with a launcher, workspace indicator, clock, and quick
  access to everything below.
- An **app launcher** (fuzzy search).
- A **volume/brightness OSD** popup.
- A native **lock screen** (no swaylock/hyprlock dependency).
- A **wallpaper picker**.
- A small **Ollama chat** popup for talking to a local AI model.
- A **power/session menu** and **dashboard**.

## Installing

### Arch Linux (recommended)

```sh
git clone https://github.com/dani-77/fabric-d77.git
cd fabric-d77
makepkg -si
```

Everything (Python deps, the launcher binaries, PAM setup) is installed as
real system packages — no `pip`, no manual steps afterwards.

### Void Linux

See [`void/README.md`](void/README.md) for building the `xbps-src`
packages.

### Other distros

A manual venv-based install is also supported. See the
[full install instructions](doc/README.md#installing) in the technical
README.

## Running it

Once installed, run it with:

```sh
fabric-d77
```

...or bind it to start automatically with your compositor, e.g. in
Hyprland/sway config:

```ini
exec fabric-d77
```

## Using it

Click the bar to open the **launcher**, or use the keybinds below to reach
everything else. Most features are popups: press the key again (or click
elsewhere) to close them.

## Keybinds

fabric-d77 doesn't grab keys itself — you bind these in your compositor
config (Hyprland/sway shown below), and it reacts to the signal.

| Action              | Suggested bind           | Command                                                   |
|---------------------|---------------------------|------------------------------------------------------------|
| App launcher        | click the bar / `SUPER`  | `kill -s SIGUSR1 $(pgrep -f main.py)`                      |
| Power/session menu  | —                         | `kill -s SIGUSR2 $(pgrep -f main.py)`                      |
| Volume up           | `XF86AudioRaiseVolume`   | `amixer set Master 5%+ unmute` *(or RTMIN+1, see below)*  |
| Volume down         | `XF86AudioLowerVolume`   | `amixer set Master 5%-` *(or RTMIN+2)*                     |
| Mute toggle         | `XF86AudioMute`          | `amixer set Master toggle` *(or RTMIN+3)*                  |
| Brightness up       | `XF86MonBrightnessUp`    | `brightnessctl set 5%+` *(or RTMIN+4)*                     |
| Brightness down     | `XF86MonBrightnessDown`  | `brightnessctl set 5%-` *(or RTMIN+5)*                     |
| Wallpaper picker    | `SUPER + W`              | `kill -s SIGRTMIN+6 $(pgrep -f main.py)`                   |
| Dashboard           | `SUPER + D`              | `kill -s SIGRTMIN+7 $(pgrep -f main.py)`                   |
| Lock screen         | `SUPER + L`              | `kill -s SIGRTMIN+8 $(pgrep -f main.py)`                   |
| Ollama chat         | `SUPER + O`               | `kill -s SIGRTMIN+9 $(pgrep -f main.py)`                   |

Example Hyprland/sway snippet:

```ini
bindl  = , SUPER, exec, kill -s SIGUSR1 $(pgrep -f main.py)
bindl  = , SUPER, W, exec, kill -s SIGRTMIN+6 $(pgrep -f main.py)
bindl  = , SUPER, D, exec, kill -s SIGRTMIN+7 $(pgrep -f main.py)
bindl  = , SUPER, L, exec, kill -s SIGRTMIN+8 $(pgrep -f main.py)
bindl  = , SUPER, O, exec, kill -s SIGRTMIN+9 $(pgrep -f main.py)
```

> If you also use an idle daemon (swayidle, hypridle...) to auto-lock the
> screen, read the note on the safer `fabric-d77-signal` helper in
> [`doc/README.md`](doc/README.md#idle-daemons-swayidle-hypridle-) — sending
> the raw `pgrep`/`kill` command straight from an idle daemon has a known
> footgun.

## More

For requirements, troubleshooting, and how each feature (lock screen, OSD,
Ollama chat, packaging) works under the hood, see the
[technical documentation in `doc/README.md`](doc/README.md).

Enjoy 🎉
