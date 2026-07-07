import math
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib, GtkLayerShell

from fabric.utils import get_relative_path
from fabric.widgets.wayland import WaylandWindow

import wallpaper_state

# ══════════════════════════════════════════════════════
# THEME (Tokyo Night) — mirrors wallpaper_selector.py / bar.py
# ══════════════════════════════════════════════════════
COL_BG = (0x1A / 255, 0x1B / 255, 0x26 / 255)
# Qt.darker(#bb9af7, 220) / Qt.darker(#bb9af7, 140), mesma fórmula (HSV,
# escala só o V) usada no Backdrop.qml original, para o visual bater certo.
COL_CHEVRON_BACK = (0x55 / 255, 0x46 / 255, 0x70 / 255)
COL_CHEVRON_FRONT = (0x86 / 255, 0x6E / 255, 0xB0 / 255)

LOGO_PATH = get_relative_path("assets/d77-logo.png")
LOGO_SIZE = 180
LOGO_MARGIN = 48
LOGO_OPACITY = 0.25


class Backdrop(WaylandWindow):
    """Fundo decorativo mostrado apenas enquanto não houver wallpaper.

    Réplica do backdrop/Backdrop.qml do quickshell-d77, mas desenhado com
    Cairo num Gtk.DrawingArea em vez de QML: o GTK3 não suporta rotação de
    widgets via CSS (transform: rotate não existe no motor CSS do GTK3),
    por isso os dois chevrons são desenhados diretamente, replicando a
    mesma matemática (rotação em torno do centro do retângulo, tal como o
    transformOrigin: Item.Center por omissão do QML).

    Fica na camada "bottom" do layer-shell — acima da camada "background"
    onde o awww-daemon desenha o wallpaper real. Não intercepta cliques
    (pass_through=True).
    """

    def __init__(self, **kwargs):
        self._logo_pixbuf = self._load_logo()

        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.connect("draw", self._on_draw)

        super().__init__(
            layer="bottom",
            anchor="top bottom left right",
            exclusivity="none",
            pass_through=True,
            child=self.drawing_area,
            visible=False,
            **kwargs,
        )

        # exclusivity="none" só significa que ESTA janela não reserva zona
        # exclusiva própria — mas por omissão ainda respeita a zona
        # reservada por OUTRAS camadas (ex.: a barra), encolhendo-se para
        # não a sobrepor. Como isto é só decoração atrás de tudo (layer
        # "bottom"), não interessa sobrepor-se à barra — ela desenha-se por
        # cima na mesma. exclusive_zone=-1 é o valor especial do protocolo
        # layer-shell para "ignora zonas exclusivas de outras camadas",
        # equivalente ao WlrLayershell.exclusionMode: Ignore do Backdrop.qml.
        GtkLayerShell.set_exclusive_zone(self, -1)

        # Construímos com visible=False (a visibilidade real só é decidida
        # a seguir, em _sync_visibility) — mas isso significa que o GTK
        # nunca chamou show_all(), e um widget filho começa por omissão
        # invisível (visible=False), independentemente do estado da janela
        # que o contém. set_visible() na janela só afeta a própria janela,
        # não os filhos, por isso sem isto o drawing_area nunca chegaria a
        # ser desenhado. Só precisa de correr uma vez.
        self.drawing_area.show()

        self._watch_state_file()
        self._sync_visibility()

    def _load_logo(self) -> GdkPixbuf.Pixbuf | None:
        try:
            return GdkPixbuf.Pixbuf.new_from_file(LOGO_PATH)
        except GLib.Error as exc:
            print(f"[backdrop] falhou a carregar '{LOGO_PATH}': {exc}")
            return None

    # -- visibilidade reativa ------------------------------------------------

    def _watch_state_file(self):
        """Observa o diretório do stateFile (Gio.FileMonitor não consegue
        vigiar um ficheiro que ainda não existe de forma fiável em todos os
        backends, por isso vigiamos o diretório-pai e filtramos pelo nome).
        """
        os.makedirs(wallpaper_state.STATE_DIR, exist_ok=True)
        gfile = Gio.File.new_for_path(wallpaper_state.STATE_DIR)
        self._monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_state_dir_changed)

    def _on_state_dir_changed(self, monitor, file, other_file, event_type):
        if file.get_basename() != os.path.basename(wallpaper_state.STATE_FILE):
            return
        self._sync_visibility()

    def _sync_visibility(self):
        has_wallpaper = wallpaper_state.read_current() is not None
        self.set_visible(not has_wallpaper)

    # -- desenho --------------------------------------------------------------

    def _on_draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()

        cr.set_source_rgb(*COL_BG)
        cr.paint()

        self._draw_chevron(cr, w, h, 0.68, -0.3, 0.8, 1.6, COL_CHEVRON_BACK)
        self._draw_chevron(cr, w, h, 0.84, -0.2, 0.4, 1.3, COL_CHEVRON_FRONT)
        self._draw_logo(cr, h)

        return False

    def _draw_chevron(self, cr, w, h, fx, fy, fw, fh, color):
        """Retângulo rodado 35°, réplica das Rectangle do Backdrop.qml.

        fx/fy/fw/fh são frações de w/h (x, y, width, height em coordenadas
        QML, topo-esquerda). A rotação em QML acontece em torno do centro
        do próprio item (transformOrigin default), por isso traduzimos
        para o centro antes de rodar.
        """
        rw, rh = fw * w, fh * h
        cx, cy = fx * w + rw / 2, fy * h + rh / 2

        cr.save()
        cr.translate(cx, cy)
        cr.rotate(math.radians(35))
        cr.set_source_rgb(*color)
        cr.rectangle(-rw / 2, -rh / 2, rw, rh)
        cr.fill()
        cr.restore()

    def _draw_logo(self, cr, h):
        if self._logo_pixbuf is None:
            return

        scaled = self._logo_pixbuf.scale_simple(
            LOGO_SIZE, LOGO_SIZE, GdkPixbuf.InterpType.BILINEAR
        )
        x = LOGO_MARGIN
        y = h - LOGO_MARGIN - LOGO_SIZE

        cr.save()
        Gdk.cairo_set_source_pixbuf(cr, scaled, x, y)
        cr.paint_with_alpha(LOGO_OPACITY)
        cr.restore()
