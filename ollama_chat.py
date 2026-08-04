import json
import os
import re
import subprocess
import threading
import time
import requests
from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.entry import Entry
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from fabric.widgets.wayland import WaylandWindow as Window
from gi.repository import GLib, Gtk

OLLAMA_BASE = "http://127.0.0.1:11434"
STATUS_POLL_SECONDS = 5
CONFIG_DIR = os.path.expanduser("~/.config/ollama-chat")
CONFIG_FILE = os.path.join(CONFIG_DIR, "model.conf")
FALLBACK_MODEL = "qwen2.5:0.5b"
INSTALL_SENTINEL = "+ install new model..."

# Used when a dedicated GPU is found but its VRAM can't be queried directly
# (e.g. AMD card without rocm-smi installed).
GPU_UNKNOWN_VRAM_MB = 4096

# (min_vram_mb, recommended_size_b), ascending by VRAM. Sized against the
# qwen2.5 family already used as FALLBACK_MODEL (0.5b .. 72b).
SIZE_TIERS = [
    (0, 0.5),
    (2048, 1.5),
    (4096, 3),
    (6144, 7),
    (10240, 14),
    (20480, 32),
    (40960, 72),
]

_MODEL_SIZE_RE = re.compile(r":(\d+(?:\.\d+)?)b\b", re.IGNORECASE)


def detect_gpu():
    """Best-effort dedicated GPU detection. Returns (vendor, vram_mb) or (None, 0)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            vram_mb = int(result.stdout.strip().splitlines()[0])
            return "nvidia", vram_mb
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        pass

    try:
        result = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            lowered = line.lower()
            if "vga" not in lowered and "3d controller" not in lowered:
                continue
            if "intel" in lowered:
                continue  # Intel iGPUs aren't dedicated
            vendor = "amd" if "amd" in lowered or "ati" in lowered else "gpu"
            return vendor, GPU_UNKNOWN_VRAM_MB
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    return None, 0


def recommend_model_size_b(vram_mb):
    size_b = SIZE_TIERS[0][1]
    for min_vram, tier_size_b in SIZE_TIERS:
        if vram_mb >= min_vram:
            size_b = tier_size_b
    return size_b


def parse_model_size_b(name):
    match = _MODEL_SIZE_RE.search(name)
    return float(match.group(1)) if match else None


class OllamaChat(Box):
    def __init__(self, **kwargs):
        super().__init__(orientation="v", spacing=6, name="ollama-chat", **kwargs)

        self.saved_model = self.load_saved_model()
        self.current_model = FALLBACK_MODEL
        self.models_loaded = False
        self.installing = False
        self.install_cancelled = False
        self.first_run_checked = False
        self._install_response = None
        self.generating = False
        self.generation_cancelled = False
        self._chat_response = None

        self.gpu_vendor = None
        self.gpu_vram_mb = 0
        self.recommended_size_b = None

        self.status_dot = Label(label="●", name="ollama-status")
        self.status_dot.get_style_context().add_class("status-unknown")

        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.append_text(FALLBACK_MODEL)
        self.model_combo.append_text(INSTALL_SENTINEL)
        self.model_combo.set_active(0)
        self.model_combo.connect("changed", self.on_model_changed)

        # Text only shows up here when something is happening (pull in progress, error, etc.)
        self.info_label = Label(label="", h_align="start", h_expand=True)
        self.info_label.set_no_show_all(True)
        self.info_label.hide()

        self.cancel_button = Button(label="Cancel", on_clicked=self.on_cancel_install)
        self.cancel_button.set_no_show_all(True)
        self.cancel_button.hide()

        self.info_row = Box(orientation="h", spacing=6)
        self.info_row.add(self.info_label)
        self.info_row.add(self.cancel_button)

        self.install_entry = Entry(placeholder="model-name:tag (e.g. llama3.2:3b)")
        self.install_entry.set_no_show_all(True)
        self.install_entry.hide()
        self.install_entry.connect("activate", self.on_install_submit)

        header = Box(orientation="h", spacing=6)
        header.add(self.status_dot)
        header.add(Label(label="Ollama"))
        header.add(self.model_combo)

        self.output = Label(label="", line_wrap="word", h_align="start")
        self.output.set_selectable(True)
        self.scroll = ScrolledWindow(
            child=self.output,
            min_content_size=(360, 320),
            max_content_size=(360, 320),
            v_expand=True,
        )
        self.entry = Entry(placeholder="Ask the AI...", on_activate=self.on_submit, h_expand=True)
        self.stop_button = Button(label="Stop", on_clicked=self.on_stop_generation)
        self.stop_button.set_no_show_all(True)
        self.stop_button.hide()

        self.prompt_row = Box(orientation="h", spacing=6)
        self.prompt_row.add(self.entry)
        self.prompt_row.add(self.stop_button)

        self.add(header)
        self.add(self.info_row)
        self.add(self.install_entry)
        self.add(self.scroll)
        self.add(self.prompt_row)

        threading.Thread(target=self.detect_hardware, daemon=True).start()
        self.start_status_polling()
        self.refresh_model_list()

    # ---------- Config ----------

    def load_saved_model(self):
        try:
            with open(CONFIG_FILE) as f:
                return f.read().strip() or None
        except FileNotFoundError:
            return None

    def save_model(self, model):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            f.write(model)

    # ---------- Hardware detection ----------

    def detect_hardware(self):
        vendor, vram_mb = detect_gpu()
        size_b = recommend_model_size_b(vram_mb)
        GLib.idle_add(self.set_hardware_info, vendor, vram_mb, size_b)

    def set_hardware_info(self, vendor, vram_mb, size_b):
        self.gpu_vendor = vendor
        self.gpu_vram_mb = vram_mb
        self.recommended_size_b = size_b
        return False

    def hardware_description(self):
        if self.gpu_vendor == "nvidia":
            return f"NVIDIA GPU detected ({self.gpu_vram_mb}MB VRAM)"
        if self.gpu_vendor:
            return "Dedicated GPU detected"
        return "No dedicated GPU detected (CPU-only)"

    def pick_model_for_hardware(self, models):
        sized = [(parse_model_size_b(m), m) for m in models]
        sized = [(size, m) for size, m in sized if size is not None]
        if not sized:
            return FALLBACK_MODEL if FALLBACK_MODEL in models else models[0]

        fitting = [(size, m) for size, m in sized if size <= self.recommended_size_b]
        if fitting:
            return max(fitting, key=lambda item: item[0])[1]
        return min(sized, key=lambda item: item[0])[1]

    # ---------- First-run auto install ----------

    def try_first_run_install(self):
        """Ollama is up but has zero models and nothing was ever chosen before.
        If there's internet, auto-pull FALLBACK_MODEL so chat works out of the box."""
        try:
            requests.head("https://ollama.com", timeout=4)
        except requests.exceptions.RequestException:
            return
        GLib.idle_add(self.start_first_run_install)

    def start_first_run_install(self):
        if self.installing or self.saved_model is not None:
            return False
        self.installing = True
        self.show_cancel_button()
        self.show_info(
            f"No models installed — downloading '{FALLBACK_MODEL}' automatically "
            f"so chat works out of the box. Click Cancel to stop."
        )
        threading.Thread(target=self.pull_model, args=(FALLBACK_MODEL,), daemon=True).start()
        return False

    # ---------- Info label (only shown when relevant) ----------

    def show_info(self, text):
        self.info_label.set_label(text)
        self.info_label.set_no_show_all(False)
        self.info_label.show()

    def hide_info(self):
        self.info_label.hide()

    def show_cancel_button(self):
        self.cancel_button.set_no_show_all(False)
        self.cancel_button.show()

    def hide_cancel_button(self):
        self.cancel_button.hide()

    def show_stop_button(self):
        self.stop_button.set_no_show_all(False)
        self.stop_button.show()

    def hide_stop_button(self):
        self.stop_button.hide()

    def on_stop_generation(self, button):
        self.generation_cancelled = True
        if self._chat_response is not None:
            try:
                self._chat_response.close()
            except Exception:
                pass
        self.hide_stop_button()

    # ---------- Model list ----------

    def refresh_model_list(self):
        def fetch():
            try:
                resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
            except Exception:
                models = None
            GLib.idle_add(self.populate_model_combo, models)

        threading.Thread(target=fetch, daemon=True).start()

    def populate_model_combo(self, models):
        if self.installing:
            return False  # don't touch the combo mid-pull

        if models is None:
            GLib.timeout_add_seconds(5, lambda: self.refresh_model_list() or False)
            return False

        self.models_loaded = True
        models_available = bool(models)

        if not models_available and self.saved_model is None and not self.first_run_checked:
            self.first_run_checked = True
            threading.Thread(target=self.try_first_run_install, daemon=True).start()

        self.model_combo.remove_all()

        if not models:
            models = [FALLBACK_MODEL]

        hardware_suggested = False
        if self.saved_model in models:
            chosen = self.saved_model
        elif self.recommended_size_b is not None:
            chosen = self.pick_model_for_hardware(models)
            hardware_suggested = True
        elif FALLBACK_MODEL in models:
            chosen = FALLBACK_MODEL
        else:
            chosen = models[0]

        self.current_model = chosen
        if models_available:
            self.save_model(chosen)

        if hardware_suggested:
            self.show_info(f"{self.hardware_description()} — auto-selected '{chosen}'.")
            GLib.timeout_add_seconds(8, lambda: self.hide_info() or False)

        active_index = 0
        for i, name in enumerate(models):
            self.model_combo.append_text(name)
            if name == chosen:
                active_index = i
        self.model_combo.append_text(INSTALL_SENTINEL)
        self.model_combo.set_active(active_index)
        return False

    def on_model_changed(self, combo):
        selected = combo.get_active_text()
        if selected == INSTALL_SENTINEL:
            self.install_entry.set_no_show_all(False)
            self.install_entry.show()
            self.install_entry.grab_focus()
            return
        if selected and self.models_loaded:
            self.current_model = selected
            self.saved_model = selected
            self.save_model(selected)
            self.hide_info()

    # ---------- Install new model ----------

    def on_install_submit(self, entry):
        model_name = entry.get_text().strip()
        entry.set_text("")
        self.install_entry.hide()
        if not model_name or self.installing:
            return
        self.installing = True
        self.show_cancel_button()
        threading.Thread(target=self.pull_model, args=(model_name,), daemon=True).start()

    def on_cancel_install(self, button):
        self.install_cancelled = True
        if self._install_response is not None:
            try:
                self._install_response.close()
            except Exception:
                pass
        self.hide_cancel_button()

    def pull_model(self, model_name):
        self.install_cancelled = False
        self._install_response = None
        try:
            resp = requests.post(
                f"{OLLAMA_BASE}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=None,
            )
            self._install_response = resp
            resp.raise_for_status()
            for line in resp.iter_lines():
                if self.install_cancelled:
                    break
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    GLib.idle_add(self.show_info, f"Error installing '{model_name}': {chunk['error']}")
                    GLib.idle_add(self.finish_install, None)
                    return

                status = chunk.get("status", "")
                total = chunk.get("total")
                completed = chunk.get("completed")
                if total and completed:
                    pct = int(completed / total * 100)
                    GLib.idle_add(self.show_info, f"Installing '{model_name}': {status} ({pct}%)")
                else:
                    GLib.idle_add(self.show_info, f"Installing '{model_name}': {status}")

            if self.install_cancelled:
                GLib.idle_add(self.show_info, f"Installation of '{model_name}' cancelled.")
                GLib.idle_add(self.finish_install, None)
                return

            GLib.idle_add(self.show_info, f"'{model_name}' installed successfully.")
            GLib.idle_add(self.finish_install, model_name)

        except requests.exceptions.ConnectionError:
            if self.install_cancelled:
                GLib.idle_add(self.show_info, f"Installation of '{model_name}' cancelled.")
            else:
                GLib.idle_add(self.show_info, "Ollama isn't running — couldn't install.")
            GLib.idle_add(self.finish_install, None)
        except Exception as e:
            if self.install_cancelled:
                GLib.idle_add(self.show_info, f"Installation of '{model_name}' cancelled.")
            else:
                GLib.idle_add(self.show_info, f"Unexpected error installing '{model_name}': {e}")
            GLib.idle_add(self.finish_install, None)
        finally:
            self._install_response = None

    def finish_install(self, new_model):
        self.installing = False
        self.hide_cancel_button()
        if new_model:
            self.saved_model = new_model
        self.refresh_model_list()
        # hide the success message after a while
        GLib.timeout_add_seconds(6, lambda: self.hide_info() or False)
        return False

    # ---------- Status ----------

    def start_status_polling(self):
        def poll():
            while True:
                is_up = self.check_ollama_status()
                GLib.idle_add(self.update_status_dot, is_up)
                time.sleep(STATUS_POLL_SECONDS)

        threading.Thread(target=poll, daemon=True).start()

    def check_ollama_status(self):
        try:
            requests.get(f"{OLLAMA_BASE}/api/version", timeout=2)
            return True
        except requests.exceptions.RequestException:
            return False

    def update_status_dot(self, is_up):
        ctx = self.status_dot.get_style_context()
        ctx.remove_class("status-up")
        ctx.remove_class("status-down")
        ctx.remove_class("status-unknown")
        ctx.add_class("status-up" if is_up else "status-down")
        if is_up and not self.models_loaded:
            self.refresh_model_list()
        return False

    # ---------- Chat ----------

    def on_submit(self, entry):
        prompt = entry.get_text().strip()
        if not prompt or self.generating:
            return
        entry.set_text("")
        self.append_text(f"\n> {prompt}\n")
        self.generating = True
        self.generation_cancelled = False
        self.show_stop_button()
        threading.Thread(target=self.query_ollama, args=(prompt,), daemon=True).start()

    def query_ollama(self, prompt):
        self._chat_response = None
        try:
            resp = requests.post(
                f"{OLLAMA_BASE}/api/generate",
                # keep_alive=0 unloads the model right after this reply
                # instead of idling on Ollama's server-side 5min default —
                # keeps it strictly load-on-demand.
                json={"model": self.current_model, "prompt": prompt, "stream": True, "keep_alive": 0},
                stream=True,
                timeout=60,
            )
            self._chat_response = resp
            resp.raise_for_status()
            for line in resp.iter_lines():
                if self.generation_cancelled:
                    self.append_text("\n[stopped]\n")
                    return
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    self.append_text(f"\n[model error: {chunk['error']}]\n")
                    return
                self.append_text(chunk.get("response", ""))

        except requests.exceptions.ConnectionError:
            if self.generation_cancelled:
                self.append_text("\n[stopped]\n")
            else:
                self.append_text(f"\n[Ollama isn't running or unreachable at {OLLAMA_BASE}.]\n")
        except requests.exceptions.Timeout:
            self.append_text("\n[Ollama took too long to respond — timeout]\n")
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                self.append_text(f"\n[Model '{self.current_model}' not found.]\n")
            else:
                self.append_text(f"\n[HTTP error: {e}]\n")
        except Exception as e:
            if self.generation_cancelled:
                self.append_text("\n[stopped]\n")
            else:
                self.append_text(f"\n[unexpected error: {e}]\n")
        finally:
            self._chat_response = None
            self.generating = False
            GLib.idle_add(self.hide_stop_button)

    def append_text(self, text):
        current = self.output.get_label() or ""
        self.output.set_label(current + text)


class OllamaChatWindow(Window):
    """Standalone popup hosting OllamaChat — triggered by SIGRTMIN+9 in main.py."""

    def __init__(self, **kwargs):
        super().__init__(
            layer="overlay",
            anchor="center",
            exclusivity="none",
            keyboard_mode="on-demand",
            visible=False,
            all_visible=False,
            **kwargs,
        )

        self.chat = OllamaChat()

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
                            Label(label="Ollama Chat", h_expand=True, h_align="start"),
                            Button(
                                image=Image(icon_name="window-close"),
                                tooltip_text="Exit",
                                on_clicked=lambda *_: self.set_visible(False),
                            ),
                        ],
                    ),
                    self.chat,
                ],
            )
        )
        self.add_keybinding("escape", lambda *_: self.set_visible(False))
        self.show_all()

    def toggle(self):
        if self.get_visible():
            self.set_visible(False)
        else:
            # Deferred via idle_add: opening this overlay-layer window and
            # grabbing keyboard focus on self.chat.entry synchronously inside
            # the triggering GTK event (e.g. the bar button's click handler)
            # made the compositor silently refuse to map the surface —
            # click did nothing, while SIGRTMIN+9 (which runs outside any
            # GTK event context) worked fine. Running it on a fresh main
            # loop iteration instead makes both paths behave the same.
            def _open():
                self.show_all()
                self.set_visible(True)
                self.chat.entry.grab_focus()
                return False
            GLib.idle_add(_open)
