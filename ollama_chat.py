import json
import os
import subprocess
import threading
import time
import requests
from fabric.widgets.box import Box
from fabric.widgets.entry import Entry
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import GLib, Gtk

OLLAMA_BASE = "http://127.0.0.1:11434"
STATUS_POLL_SECONDS = 5
CONFIG_DIR = os.path.expanduser("~/.config/ollama-chat")
CONFIG_FILE = os.path.join(CONFIG_DIR, "model.conf")
FALLBACK_MODEL = "qwen2.5:0.5b"
INSTALL_SENTINEL = "+ instalar novo modelo..."


class OllamaChat(Box):
    def __init__(self, **kwargs):
        super().__init__(orientation="v", spacing=6, name="ollama-chat", **kwargs)

        self.saved_model = self.load_saved_model()
        self.current_model = FALLBACK_MODEL
        self.models_loaded = False
        self.installing = False

        self.status_dot = Label(label="●", name="ollama-status")
        self.status_dot.get_style_context().add_class("status-unknown")

        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.append_text(FALLBACK_MODEL)
        self.model_combo.append_text(INSTALL_SENTINEL)
        self.model_combo.set_active(0)
        self.model_combo.connect("changed", self.on_model_changed)

        # Só aparece texto aqui quando há algo a acontecer (pull em curso, erro, etc.)
        self.info_label = Label(label="", h_align="start")
        self.info_label.set_no_show_all(True)
        self.info_label.hide()

        self.install_entry = Entry(placeholder="nome-do-modelo:tag (ex: llama3.2:3b)")
        self.install_entry.set_no_show_all(True)
        self.install_entry.hide()
        self.install_entry.connect("activate", self.on_install_submit)

        header = Box(orientation="h", spacing=6)
        header.add(self.status_dot)
        header.add(Label(label="Ollama"))
        header.add(self.model_combo)

        self.output = Label(label="", line_wrap=True, h_align="start")
        self.scroll = ScrolledWindow(child=self.output, v_expand=True)
        self.entry = Entry(placeholder="Pergunta à IA...", on_activate=self.on_submit)

        self.add(header)
        self.add(self.info_label)
        self.add(self.install_entry)
        self.add(self.scroll)
        self.add(self.entry)

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

    # ---------- Info label (só aparece quando relevante) ----------

    def show_info(self, text):
        self.info_label.set_label(text)
        self.info_label.set_no_show_all(False)
        self.info_label.show()

    def hide_info(self):
        self.info_label.hide()

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
            return False  # não mexe no combo a meio de um pull

        if models is None:
            GLib.timeout_add_seconds(5, lambda: self.refresh_model_list() or False)
            return False

        self.models_loaded = True
        self.model_combo.remove_all()

        if not models:
            models = [FALLBACK_MODEL]

        if self.saved_model in models:
            chosen = self.saved_model
        elif FALLBACK_MODEL in models:
            chosen = FALLBACK_MODEL
        else:
            chosen = models[0]

        self.current_model = chosen
        self.save_model(chosen)

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
            self.save_model(selected)
            self.hide_info()

    # ---------- Instalar novo modelo ----------

    def on_install_submit(self, entry):
        model_name = entry.get_text().strip()
        entry.set_text("")
        self.install_entry.hide()
        if not model_name:
            return
        self.installing = True
        threading.Thread(target=self.pull_model, args=(model_name,), daemon=True).start()

    def pull_model(self, model_name):
        try:
            resp = requests.post(
                f"{OLLAMA_BASE}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=None,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    GLib.idle_add(self.show_info, f"Erro a instalar '{model_name}': {chunk['error']}")
                    GLib.idle_add(self.finish_install, None)
                    return

                status = chunk.get("status", "")
                total = chunk.get("total")
                completed = chunk.get("completed")
                if total and completed:
                    pct = int(completed / total * 100)
                    GLib.idle_add(self.show_info, f"A instalar '{model_name}': {status} ({pct}%)")
                else:
                    GLib.idle_add(self.show_info, f"A instalar '{model_name}': {status}")

            GLib.idle_add(self.show_info, f"'{model_name}' instalado com sucesso.")
            GLib.idle_add(self.finish_install, model_name)

        except requests.exceptions.ConnectionError:
            GLib.idle_add(self.show_info, "Ollama não está a correr — não foi possível instalar.")
            GLib.idle_add(self.finish_install, None)
        except Exception as e:
            GLib.idle_add(self.show_info, f"Erro inesperado a instalar '{model_name}': {e}")
            GLib.idle_add(self.finish_install, None)

    def finish_install(self, new_model):
        self.installing = False
        if new_model:
            self.saved_model = new_model
        self.refresh_model_list()
        # esconde a mensagem de sucesso passado um tempo
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
            result = subprocess.run(
                ["sv", "status", "ollama"], capture_output=True, text=True, timeout=3
            )
            return result.stdout.strip().startswith("run:")
        except Exception:
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
        if not prompt:
            return
        entry.set_text("")
        self.append_text(f"\n> {prompt}\n")
        threading.Thread(target=self.query_ollama, args=(prompt,), daemon=True).start()

    def query_ollama(self, prompt):
        try:
            resp = requests.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": self.current_model, "prompt": prompt, "stream": True},
                stream=True,
                timeout=60,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    self.append_text(f"\n[erro do modelo: {chunk['error']}]\n")
                    return
                self.append_text(chunk.get("response", ""))

        except requests.exceptions.ConnectionError:
            self.append_text("\n[Ollama não está a correr. Verifica com: sv status ollama]\n")
        except requests.exceptions.Timeout:
            self.append_text("\n[Ollama demorou demasiado a responder — timeout]\n")
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                self.append_text(f"\n[Modelo '{self.current_model}' não encontrado.]\n")
            else:
                self.append_text(f"\n[erro HTTP: {e}]\n")
        except Exception as e:
            self.append_text(f"\n[erro inesperado: {e}]\n")

    def append_text(self, text):
        current = self.output.get_label() or ""
        self.output.set_label(current + text)
