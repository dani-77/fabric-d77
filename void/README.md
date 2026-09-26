# Void Linux packaging

`xbps-src` templates for installing fabric-d77 as a real system package on
Void Linux — every Python dependency comes from a system package, nothing
runs from a venv. Void has no AUR-style overlay, so using these means
dropping them into a local checkout of `void-packages`.

## One-time setup

```
git clone --depth 1 https://github.com/void-linux/void-packages.git
cd void-packages
./xbps-src binary-bootstrap
```

## Add these templates

From this repo:

```
cp -r void/srcpkgs/fabric-d77 void/srcpkgs/fabric /path/to/void-packages/srcpkgs/
```

(symlink instead of `cp` if you want `git pull` here to keep them in sync.)

## Build & install

```
cd /path/to/void-packages
./xbps-src pkg fabric
./xbps-src pkg fabric-d77
sudo xbps-install --repository=hostdir/binpkgs -R fabric-d77
```

Run it with `fabric-d77`, or bind it directly in your compositor config
(e.g. `exec fabric-d77` in Hyprland/sway).

## Notes

- These templates are copies of the ones in
  [`d77void/srcpkgs-d77`](https://github.com/d77void/srcpkgs-d77), which is
  the authoritative source.
- `fabric` isn't packaged in void-packages proper (Fabric is a git
  dependency, not a PyPI release), so it ships here alongside `fabric-d77`,
  pinned to the same commit as `requirements.txt`.
- `fabric-d77`'s template pins a specific commit of *this* repo (`_commit`,
  since there are no release tags yet). Bump it and recompute the checksum
  whenever you want to package a newer revision
  (`./xbps-src pkg fabric-d77` prints the real one on a mismatch).
- Everything else in `depends` — `python3-gobject`, `python3-cairo`,
  `python3-pam`, `python3-thefuzz`, `gtk-session-lock`, etc. — is already
  packaged in void-packages, so `xbps-src`/`xbps-install` pull it in
  automatically.
