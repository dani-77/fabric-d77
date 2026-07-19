# Maintainer: Daniel Azevedo
#
# Real Arch package for the shell: every Python dependency comes from a
# system package (repo or AUR), so nothing is fetched into a venv at
# runtime. Build and install with:
#
#   makepkg -si
#
# from inside this repository (it packages the working tree in place, no
# network fetch of the source itself).

pkgname=fabric-d77
pkgver=1.0.0
pkgrel=1
pkgdesc="GTK desktop shell for Wayland compositors, built on Fabric"
arch=('any')
url="https://github.com/dani-77/fabric-d77"
license=('MIT')
depends=(
  'python'
  'python-gobject'
  'python-cairo'
  'python-cffi'
  'python-pycparser'
  'python-click'
  'python-loguru'
  'python-pillow'
  'python-psutil'
  'python-rapidfuzz'
  'python-setproctitle'
  'python-six'
  'python-pam'
  'python-thefuzz'
  'python-fabric-git'
  'gtk-session-lock'
  'alsa-utils'
  'brightnessctl'
)
optdepends=(
  'swaylock: lock screen fallback if gtk-session-lock is unavailable'
  'hyprlock: lock screen fallback if gtk-session-lock is unavailable'
)
backup=('etc/pam.d/fabric-d77')

package() {
    cd "$startdir"

    # PAM service file + the swayidle-safe signal helper (see Makefile).
    make DESTDIR="$pkgdir" install

    install -d "$pkgdir/usr/share/$pkgname"
    cp -a -- *.py assets style.css "$pkgdir/usr/share/$pkgname/"

    install -Dm755 bin/fabric-d77 "$pkgdir/usr/bin/fabric-d77"
}
