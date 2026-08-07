<p align="center">
  <img src="doc/assets/fabric-d77-icon.png" width="128" alt="fabric-d77 icon">
</p>

<h1 align="center">fabric-d77</h1>

<p align="center">
  A simple, good-looking desktop shell — top bar, app launcher, lock screen,
  volume/brightness OSD, wallpaper picker and a local AI chat popup — for
  Wayland compositors like Hyprland and sway.
</p>

---

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

It's built on **[Fabric](https://github.com/Fabric-Development/fabric)**
and Python.

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
config (Hyprland/sway shown below), and it reacts to the signal. The
easiest way is the bundled **`fabric-d77-signal`** helper script — it ships
automatically with the Arch/Void packages, and just needs `SIGNAL` as its
one argument:

| Action              | Suggested bind           | Command                                |
|---------------------|---------------------------|------------------------------------------|
| App launcher        | click the bar / `SUPER`  | `fabric-d77-signal USR1`                 |
| Power/session menu  | —                         | `fabric-d77-signal USR2`                 |
| Volume up           | `XF86AudioRaiseVolume`   | `amixer set Master 5%+ unmute` *(or `fabric-d77-signal RTMIN+1`)* |
| Volume down         | `XF86AudioLowerVolume`   | `amixer set Master 5%-` *(or `RTMIN+2`)* |
| Mute toggle         | `XF86AudioMute`          | `amixer set Master toggle` *(or `RTMIN+3`)* |
| Brightness up       | `XF86MonBrightnessUp`    | `brightnessctl set 5%+` *(or `RTMIN+4`)* |
| Brightness down     | `XF86MonBrightnessDown`  | `brightnessctl set 5%-` *(or `RTMIN+5`)* |
| Wallpaper picker    | `SUPER + W`              | `fabric-d77-signal RTMIN+6`              |
| Dashboard           | `SUPER + D`              | `fabric-d77-signal RTMIN+7`              |
| Lock screen         | `SUPER + L`              | `fabric-d77-signal RTMIN+8`              |
| Ollama chat         | `SUPER + O`               | `fabric-d77-signal RTMIN+9`              |

Example Hyprland/sway snippet:

```ini
bindl  = , SUPER, exec, fabric-d77-signal USR1
bindl  = , SUPER, W, exec, fabric-d77-signal RTMIN+6
bindl  = , SUPER, D, exec, fabric-d77-signal RTMIN+7
bindl  = , SUPER, L, exec, fabric-d77-signal RTMIN+8
bindl  = , SUPER, O, exec, fabric-d77-signal RTMIN+9
```

> **No `fabric-d77-signal` on your system?** (only happens with a manual
> venv install — run `sudo make install` to add it, or fall back to
> `kill -s SIGRTMIN+8 $(pgrep -f main.py)`-style raw signals.) Either way,
> if you also use an idle daemon (swayidle, hypridle...) to auto-lock the
> screen, read the note on why the helper matters there in
> [`doc/README.md`](doc/README.md#idle-daemons-swayidle-hypridle-) — sending
> a raw `pgrep`/`kill` command straight from an idle daemon has a known
> footgun.

## More

For requirements, troubleshooting, and how each feature (lock screen, OSD,
Ollama chat, packaging) works under the hood, see the
[technical documentation in `doc/README.md`](doc/README.md).

## License

MIT — see [LICENSE](LICENSE).
