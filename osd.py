"""On-Screen Display (OSD) para volume, brilho e perfil de energia — fabric-d77.

Overlay minimalista (ícone + barra de progresso + percentagem) que aparece no
canto superior direito sempre que o volume, o brilho do ecrã ou o perfil de
energia mudam, e desaparece automaticamente após alguns segundos.

Backends (propositadamente independentes do servidor de áudio, à semelhança do
módulo equivalente no quickshell-d77):

* Volume  -> ALSA via ``amixer`` (com suporte a mute/unmute).
* Brilho  -> ``brightnessctl``.
* Perfil de energia -> ``powerprofilesctl``.

Funcionamento:

* Um ``Fabricator`` faz polling periódico do volume/mute, do brilho e do
  perfil de energia. Sempre que deteta uma mudança (mesmo que provocada
  externamente — por exemplo teclas multimédia ligadas diretamente ao
  ``amixer``/``brightnessctl``, ou outra app a mexer no volume/perfil) mostra o
  OSD correspondente.
* O OSD também expõe métodos públicos (:meth:`OSD.volume_up`,
  :meth:`OSD.volume_down`, :meth:`OSD.volume_mute_toggle`,
  :meth:`OSD.brightness_up`, :meth:`OSD.brightness_down`,
  :meth:`OSD.power_profile_cycle`) para quem preferir que seja a shell a
  aplicar a alteração e mostrar o OSD de imediato.

A janela é uma layer-shell ``WaylandWindow`` na camada *overlay*, ancorada ao
topo-direita, com ``pass_through=True`` para não bloquear o rato.
"""

import re
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib  # noqa: E402

from fabric.widgets.box import Box  # noqa: E402
from fabric.widgets.image import Image  # noqa: E402
from fabric.widgets.label import Label  # noqa: E402
from fabric.widgets.scale import Scale  # noqa: E402
from fabric.widgets.wayland import WaylandWindow as Window  # noqa: E402
from fabric.core.fabricator import Fabricator  # noqa: E402


# ── Configuração ────────────────────────────────────────────────────────────
MIXER_CONTROL = "Master"   # controlo ALSA usado pelo amixer
STEP = 5                   # passo (%) para subir/descer volume e brilho
TIMEOUT_MS = 2500          # tempo (ms) que o OSD fica visível
POLL_INTERVAL_MS = 300     # intervalo de polling para detetar mudanças externas


# ── Helpers de backend ──────────────────────────────────────────────────────
def _run(cmd: list[str]) -> str:
    """Corre um comando e devolve o stdout (string). Falhas devolvem "" ."""
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        ).stdout
    except Exception:
        return ""


def get_volume() -> tuple[int, bool]:
    """Lê o volume (0-100) e o estado de mute via ALSA.

    Devolve ``(nivel, muted)``. Em caso de erro devolve ``(0, False)``.
    """
    out = _run(["amixer", "get", MIXER_CONTROL])
    if not out:
        return 0, False

    level = 0
    muted = False
    for line in out.splitlines():
        if "%]" in line:
            # ex.: "  Front Left: Playback 32768 [50%] [on]"
            try:
                seg = line.split("[")[1]          # "50%] ..."
                level = int(seg.split("%")[0])
            except (IndexError, ValueError):
                pass
            if "[off]" in line:
                muted = True
            break
    return level, muted


POWER_PROFILES = ["performance", "balanced", "power-saver"]


def get_power_profile() -> str:
    """Lê o perfil de energia ativo via D-Bus (net.hadess.PowerProfiles).

    Usa ``gdbus`` (binário nativo, ~20ms) em vez de ``powerprofilesctl``
    (script Python, ~500ms) porque esta função corre em cada ciclo de
    polling (a cada :data:`POLL_INTERVAL_MS`) — com ``powerprofilesctl`` o
    tempo do próprio polling excedia o intervalo e bloqueava o GLib main
    loop, impedindo a shell inteira de renderizar janelas.

    Em caso de erro devolve "" (tratado como "indisponível").
    """
    out = _run([
        "gdbus", "call", "--system",
        "--dest", "net.hadess.PowerProfiles",
        "--object-path", "/net/hadess/PowerProfiles",
        "--method", "org.freedesktop.DBus.Properties.Get",
        "net.hadess.PowerProfiles", "ActiveProfile",
    ])
    match = re.search(r"'([^']+)'", out)
    profile = match.group(1) if match else ""
    return profile if profile in POWER_PROFILES else ""


def get_brightness() -> int:
    """Lê o brilho atual (0-100) via ``brightnessctl``.

    Usa o output legível por máquina (``-m``): campo 4 = percentagem.
    Em caso de erro devolve -1 (tratado como "indisponível").
    """
    out = _run(["brightnessctl", "-m"]).strip()
    if not out:
        return -1
    try:
        # ex.: "intel_backlight,backlight,3000,40%,7500"
        parts = out.split(",")
        return int(parts[3].rstrip("%"))
    except (IndexError, ValueError):
        return -1


class OSD(Window):
    """Janela overlay de OSD (volume + brilho)."""

    def __init__(self, **kwargs):
        # IMPORTANTE: inicializar primeiro o GObject base (WaylandWindow).
        # Como OSD herda de uma Gtk.Window (via Fabric), o objeto tem de estar
        # inicializado *antes* de criar/atribuir widgets ou adicionar filhos —
        # caso contrário o GObject lança
        # "RuntimeError: object ... of type OSD is not initialized".
        # Este é o mesmo padrão usado por SessionMenu e StatusBar.
        super().__init__(
            name="osd-window",
            layer="overlay",
            anchor="top right",
            margin="16px 16px 0px 0px",
            exclusivity="none",
            pass_through=True,   # não bloqueia eventos do rato
            visible=False,
            all_visible=False,
            **kwargs,
        )

        # ── Ícone ───────────────────────────────────────────────────────────
        self.icon = Image(
            name="osd-icon",
            icon_name="audio-volume-high-symbolic",
            icon_size=24,
        )

        # ── Barra de progresso (Scale não-interativa) ────────────────────────
        self.scale = Scale(
            name="osd-scale",
            value=0.0,
            min_value=0.0,
            max_value=100.0,
            orientation="h",
            draw_value=False,
            h_expand=True,
        )
        # Não-interativa: serve apenas como barra de progresso.
        self.scale.set_sensitive(False)

        # ── Percentagem ──────────────────────────────────────────────────────
        self.label = Label(name="osd-label", label="0%")

        # NOTA: o atributo NÃO se pode chamar ``self.container`` — esse nome
        # colide com um *field* introspetado do GObject/Gtk que é só-de-leitura,
        # provocando "RuntimeError: field is not writable". Usamos ``self.box``.
        self.box = Box(
            name="osd-box",
            orientation="h",
            spacing=12,
            children=[self.icon, self.scale, self.label],
        )

        # Adiciona o conteúdo à janela já inicializada.
        self.children = self.box

        # ── Estado ────────────────────────────────────────────────────────────
        self._hide_timer: int | None = None
        # Baseline inicial (não mostra OSD no arranque; só em mudanças futuras).
        self._last_vol, self._last_muted = get_volume()
        self._last_bri = get_brightness()
        self._last_profile = get_power_profile()

        # ── Polling para detetar mudanças externas ───────────────────────────
        self._watcher = Fabricator(
            interval=POLL_INTERVAL_MS,
            poll_from=lambda *_: (get_volume(), get_brightness(), get_power_profile()),
            on_changed=self._on_poll,
            default_value=(
                (self._last_vol, self._last_muted),
                self._last_bri,
                self._last_profile,
            ),
        )

    # ── Polling ──────────────────────────────────────────────────────────────
    def _on_poll(self, _, value):
        (vol, muted), bri, profile = value

        vol_changed = (vol != self._last_vol) or (muted != self._last_muted)
        bri_changed = (bri != self._last_bri) and (bri >= 0)
        profile_changed = (profile != self._last_profile) and profile

        # Brilho tem prioridade se ambos mudarem no mesmo ciclo (raro).
        if bri_changed:
            self._last_bri = bri
            self._show_brightness(bri)
        if vol_changed:
            self._last_vol, self._last_muted = vol, muted
            self._show_volume(vol, muted)
        if profile_changed:
            self._last_profile = profile
            self._show_power_profile(profile)

    # ── Apresentação ──────────────────────────────────────────────────────────
    def _volume_icon(self, level: int, muted: bool) -> str:
        if muted or level == 0:
            return "audio-volume-muted-symbolic"
        if level < 34:
            return "audio-volume-low-symbolic"
        if level < 67:
            return "audio-volume-medium-symbolic"
        return "audio-volume-high-symbolic"

    def _power_profile_icon(self, profile: str) -> str:
        return f"power-profile-{profile}-symbolic"

    def _brightness_icon(self, level: int) -> str:
        if level < 34:
            return "display-brightness-low-symbolic"
        if level < 67:
            return "display-brightness-medium-symbolic"
        return "display-brightness-high-symbolic"

    def _show_volume(self, level: int, muted: bool):
        self.scale.set_visible(True)
        self.icon.set_from_icon_name(self._volume_icon(level, muted), 24)
        self.scale.set_value(0 if muted else level)
        self.label.set_label("mute" if muted else f"{level}%")
        self._set_mode_class("volume", muted)
        self._reveal()

    def _show_brightness(self, level: int):
        self.scale.set_visible(True)
        self.icon.set_from_icon_name(self._brightness_icon(level), 24)
        self.scale.set_value(level)
        self.label.set_label(f"{level}%")
        self._set_mode_class("brightness", False)
        self._reveal()

    def _show_power_profile(self, profile: str):
        # Perfil de energia é um estado discreto, não uma percentagem —
        # esconde a barra de progresso e mostra só ícone + nome.
        self.scale.set_visible(False)
        self.icon.set_from_icon_name(self._power_profile_icon(profile), 24)
        self.label.set_label(profile.replace("-", " ").title())
        self._set_mode_class("power", False)
        self._reveal()

    def _set_mode_class(self, mode: str, muted: bool):
        # Permite estilizar volume/brilho/mute/power de forma diferente via CSS.
        for cls in ("volume", "brightness", "power", "muted"):
            self.box.remove_style_class(cls)
            self.scale.remove_style_class(cls)
        self.box.add_style_class(mode)
        self.scale.add_style_class(mode)
        if muted:
            self.box.add_style_class("muted")
            self.scale.add_style_class("muted")

    def _reveal(self):
        self.set_visible(True)
        if self._hide_timer is not None:
            GLib.source_remove(self._hide_timer)
        self._hide_timer = GLib.timeout_add(TIMEOUT_MS, self._hide)

    def _hide(self):
        self.set_visible(False)
        self._hide_timer = None
        return False  # não repetir o timeout

    # ── API pública (a shell pode aplicar a alteração e mostrar o OSD) ────────
    def volume_up(self, *_):
        _run(["amixer", "set", MIXER_CONTROL, f"{STEP}%+", "unmute"])
        self._refresh_volume()

    def volume_down(self, *_):
        _run(["amixer", "set", MIXER_CONTROL, f"{STEP}%-"])
        self._refresh_volume()

    def volume_mute_toggle(self, *_):
        _run(["amixer", "set", MIXER_CONTROL, "toggle"])
        self._refresh_volume()

    def brightness_up(self, *_):
        _run(["brightnessctl", "set", f"{STEP}%+"])
        self._refresh_brightness()

    def brightness_down(self, *_):
        _run(["brightnessctl", "set", f"{STEP}%-"])
        self._refresh_brightness()

    def power_profile_cycle(self, *_):
        current = get_power_profile() or self._last_profile
        try:
            next_profile = POWER_PROFILES[(POWER_PROFILES.index(current) + 1) % len(POWER_PROFILES)]
        except ValueError:
            next_profile = POWER_PROFILES[0]
        _run(["powerprofilesctl", "set", next_profile])
        self._refresh_power_profile()

    def _refresh_volume(self):
        vol, muted = get_volume()
        self._last_vol, self._last_muted = vol, muted
        self._show_volume(vol, muted)

    def _refresh_brightness(self):
        bri = get_brightness()
        if bri >= 0:
            self._last_bri = bri
            self._show_brightness(bri)

    def _refresh_power_profile(self):
        profile = get_power_profile()
        if profile:
            self._last_profile = profile
            self._show_power_profile(profile)


if __name__ == "__main__":
    # Execução autónoma para testar o OSD (fora da shell principal).
    from fabric import Application
    from fabric.utils import get_relative_path

    osd = OSD()
    app = Application("d77-osd", osd)

    style_path = get_relative_path("./style.css")
    try:
        app.set_stylesheet_from_file(style_path)
    except Exception:
        pass

    app.run()
