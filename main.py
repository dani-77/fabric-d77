import os
import signal
from fabric import Application
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.utils import get_relative_path

# Importamos as classes originais dos teus ficheiros
from bar import StatusBar
from launcher import AppLauncher

class MainStatusBar(StatusBar):
    def __init__(self, launcher_window: AppLauncher):
        self.launcher = launcher_window
        super().__init__()

    def show_all(self):
        # 1. Criamos o botão do Launcher
        launcher_button = Button(
            name="launcher-button",
            child=Image(icon_name="view-app-grid-symbolic", icon_size=14),
            on_clicked=lambda *_: self.toggle_launcher(),
        )

        # 2. Injetamos o botão no início do left_container
        if hasattr(self, "main_layout") and len(self.main_layout.children) > 0:
            left_container = self.main_layout.children[0]
            current_children = left_container.children
            current_children.insert(0, launcher_button)
            left_container.children = current_children

        # 3. Executa o comportamento normal de exibição da barra
        return super().show_all()

    def toggle_launcher(self):
        if self.launcher.get_visible():
            self.launcher.set_visible(False)
        else:
            # 1. Primeiro redesenhamos os componentes internos do launcher
            self.launcher.show_all()
            # 2. Forçamos a atualização da lista de aplicações
            self.launcher.refresh_apps()
            # 3. Tornamos a janela visível e damos foco
            self.launcher.set_visible(True)
            self.launcher.search_entry.grab_focus()


if __name__ == "__main__":
    # 1. Inicializa o Launcher
    launcher = AppLauncher()
    
    # Garante que inicia escondido
    launcher.set_visible(False)
    
    # Substitui o atalho de Escape do launcher para APENAS ESCONDER
    launcher.add_keybinding("escape", lambda: launcher.set_visible(False))
    
    # 2. Inicializa a Barra passando a referência do launcher
    bar = MainStatusBar(launcher_window=launcher)

    # 3. Cria a aplicação unificada carregando os estilos
    app = Application("d77-shell", [bar, launcher])

    signal.signal(signal.SIGUSR1, lambda signum, frame: bar.toggle_launcher())    

    # Carrega o teu estilo CSS existente
    style_path = get_relative_path("./style.css")
    if os.path.exists(style_path):
        app.set_stylesheet_from_file(style_path)

    app.run()
