#!/usr/bin/env bash

DIR="$HOME/.config/fabric-d77"
VENV="$DIR/venv"
LOG="$DIR/setup.log"

if [ ! -d "$VENV" ]; then
    notify-send "fabric-d77" "A instalar dependências, aguarda..." 2>/dev/null || true
    python3 -m venv "$VENV" >"$LOG" 2>&1
    "$VENV/bin/pip" install --upgrade pip >>"$LOG" 2>&1
    "$VENV/bin/pip" install -r "$DIR/requirements.txt" >>"$LOG" 2>&1
    notify-send "fabric-d77" "Setup concluído." 2>/dev/null || true
fi

source "$VENV/bin/activate"
exec python "$DIR/main.py"
