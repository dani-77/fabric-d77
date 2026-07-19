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
cp -r void/srcpkgs/fabric-d77 void/srcpkgs/python3-fabric /path/to/void-packages/srcpkgs/
```

(symlink instead of `cp` if you want `git pull` here to keep them in sync.)

## Build & install

```
cd /path/to/void-packages
./xbps-src pkg python3-fabric
./xbps-src pkg fabric-d77
sudo xbps-install --repository=hostdir/binpkgs -R fabric-d77
```

Run it with `fabric-d77`, or bind it directly in your compositor config
(e.g. `exec fabric-d77` in Hyprland/sway).

## Notes

- `python3-fabric` isn't packaged in void-packages proper (Fabric is a git
  dependency, not a PyPI release), so it ships here alongside `fabric-d77`.
  Its `checksum` is a placeholder — building offline for this repo, there
  was no access to `Fabric-Development/fabric` to compute the real sha256.
  Run `./xbps-src pkg python3-fabric` once; it fetches the tarball, fails
  on the checksum mismatch, and prints the real sha256 to paste in.
- `fabric-d77`'s template pins a specific commit of *this* repo (`_commit`,
  since there are no release tags yet). Bump it and recompute the checksum
  the same way whenever you want to package a newer revision.
- Everything else in `depends` — `python3-gobject`, `python3-cairo`,
  `python3-pam`, `python3-thefuzz`, `gtk-session-lock`, etc. — is already
  packaged in void-packages, so `xbps-src`/`xbps-install` pull it in
  automatically.
