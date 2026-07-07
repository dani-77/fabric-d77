#!/bin/sh
# apply-saved-wallpaper.sh (fabric-d77 / awww)
#
# Aplica o último wallpaper escolhido no picker (wallpaper_selector.py) mal
# o awww-daemon arranque, ou pinta o colBg do Backdrop se não houver nenhum
# guardado (ou tiver sido feito "Clear"). Ao contrário do hyprpaper, o awww
# não tem um ficheiro de config para pré-carregar antes do daemon arrancar:
# tudo é feito via comandos IPC a um daemon já a correr, por isso este
# script tem de correr DEPOIS do "awww-daemon" no exec-once, e espera pelo
# socket ficar pronto antes de mandar o comando.
#
# Run this from hyprland config, DEPOIS de "awww-daemon -l background":
#   exec-once = awww-daemon -l background
#   exec-once = sh ~/.config/fabric-d77/apply-saved-wallpaper.sh
#
# Written in plain POSIX sh: no seq, no fractional sleep, no bashisms.

STATE_FILE="$HOME/.cache/fabric-d77/wallpaper/current"
CLEAR_COLOR="1a1b26"

# Espera o socket do awww-daemon ficar pronto (arranca em paralelo via
# exec-once separado, pode ainda não ter inicializado).
i=0
while [ "$i" -lt 10 ]; do
    awww query >/dev/null 2>&1 && break
    i=$((i + 1))
    sleep 1
done

WALLPAPER=""
if [ -f "$STATE_FILE" ]; then
    WALLPAPER="$(cat "$STATE_FILE")"
    [ -f "$WALLPAPER" ] || WALLPAPER=""
fi

if [ -n "$WALLPAPER" ]; then
    awww img "$WALLPAPER"
else
    awww clear "$CLEAR_COLOR"
fi
