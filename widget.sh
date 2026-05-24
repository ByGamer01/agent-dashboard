#!/bin/bash
# Abre el dashboard como ventana flotante sin barra de navegador
# Puedes moverla y redimensionarla como cualquier app

# Asegura que el servidor está corriendo
if ! lsof -ti:7788 > /dev/null 2>&1; then
  echo "Iniciando servidor..."
  cd "$(dirname "$0")" && python3 server.py &
  sleep 2
fi

# Abre en modo app (sin barra de navegador) — parece una app nativa
open -na "Google Chrome" --args \
  --app=http://127.0.0.1:7788 \
  --window-size=1200,750 \
  --window-position=80,80 \
  --disable-extensions \
  --no-first-run
