# Agent Dashboard

`agent-dashboard` es un panel local para visualizar actividad de agentes de IA en tiempo real. Levanta un servidor FastAPI, observa logs y procesos locales de distintos agentes, y renderiza una sala de control animada en HTML Canvas donde cada agente aparece como un robot con estado, color, movimiento, particulas y burbujas de actividad.

El proyecto esta pensado para correr en local, en la maquina del usuario, sin base de datos y sin servicios externos. Su objetivo es ofrecer una vista rapida y visual de que agentes estan activos, cuantos procesos hay por agente y cual fue la ultima linea relevante detectada en sus logs.

## Tabla de contenidos

- [Caracteristicas principales](#caracteristicas-principales)
- [Vista general](#vista-general)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Requisitos](#requisitos)
- [Instalacion](#instalacion)
- [Uso rapido](#uso-rapido)
- [Como funciona](#como-funciona)
- [Agentes soportados](#agentes-soportados)
- [Estados del agente](#estados-del-agente)
- [Servidor backend](#servidor-backend)
- [Frontend Canvas](#frontend-canvas)
- [WebSocket](#websocket)
- [Script de ventana flotante](#script-de-ventana-flotante)
- [Configuracion](#configuracion)
- [Personalizacion](#personalizacion)
- [Troubleshooting](#troubleshooting)
- [Desarrollo](#desarrollo)
- [Seguridad y privacidad](#seguridad-y-privacidad)
- [Limitaciones conocidas](#limitaciones-conocidas)
- [Roadmap sugerido](#roadmap-sugerido)

## Caracteristicas principales

- Dashboard visual en tiempo real.
- Backend local con FastAPI.
- Canal WebSocket para enviar cambios de estado al navegador.
- Renderizado completo con HTML Canvas, sin framework frontend.
- Robots animados para cada agente.
- Soporte inicial para Hermes, Claude Code y Codex.
- Deteccion de multiples instancias por agente inspeccionando procesos locales con `ps aux`.
- Lectura de logs locales para inferir actividad.
- Transiciones automaticas entre estados `working`, `thinking` e `idle`.
- Script `widget.sh` para abrir el dashboard como ventana tipo app en Google Chrome.
- Sin base de datos, sin build step y sin dependencias frontend.

## Vista general

El dashboard esta formado por tres piezas:

1. `server.py`: servidor Python que expone la pagina web y un WebSocket.
2. `index.html`: experiencia visual animada con Canvas y JavaScript puro.
3. `widget.sh`: helper para macOS que arranca el servidor si hace falta y abre Chrome en modo app.

Flujo simplificado:

```text
Logs y procesos locales
        |
        v
server.py
  - lee logs
  - cuenta procesos
  - calcula estados
  - emite JSON por WebSocket
        |
        v
index.html
  - recibe estados
  - sincroniza robots
  - dibuja la sala animada
```

## Estructura del proyecto

```text
agent-dashboard/
├── index.html   # Interfaz visual, animaciones y cliente WebSocket
├── server.py    # Backend FastAPI y monitor de agentes
└── widget.sh    # Lanzador macOS para abrir el dashboard como app
```

El repositorio no incluye por ahora:

- `requirements.txt`
- `pyproject.toml`
- tests automatizados
- configuracion externa
- assets estaticos adicionales

Todo el frontend vive dentro de `index.html`, y todo el backend vive dentro de `server.py`.

## Requisitos

### Sistema

El proyecto esta orientado a macOS, especialmente por el script `widget.sh`, que usa:

- `lsof`
- `open`
- Google Chrome

El servidor en si puede ejecutarse en otros sistemas si Python y las dependencias estan disponibles, pero el script de apertura como ventana flotante esta escrito para macOS.

### Python

Requiere Python 3.10 o superior recomendado.

Dependencias Python:

```bash
fastapi
uvicorn
```

### Navegador

Para usar `widget.sh` necesitas Google Chrome instalado. Tambien puedes abrir manualmente el dashboard en cualquier navegador moderno entrando a:

```text
http://127.0.0.1:7788
```

## Instalacion

Desde la carpeta del proyecto:

```bash
cd /Users/david/agent-dashboard
```

Crea un entorno virtual, opcional pero recomendado:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Instala las dependencias:

```bash
pip install fastapi uvicorn
```

Como el proyecto no incluye un `requirements.txt`, esas son las dependencias directas que necesita `server.py`.

## Uso rapido

### Opcion 1: ejecutar el servidor manualmente

```bash
cd /Users/david/agent-dashboard
python3 server.py
```

Luego abre:

```text
http://127.0.0.1:7788
```

El servidor escucha en:

```text
127.0.0.1:7788
```

### Opcion 2: abrir como widget/app de Chrome

```bash
cd /Users/david/agent-dashboard
./widget.sh
```

Este script:

1. Comprueba si ya hay algo escuchando en el puerto `7788`.
2. Si no hay servidor, ejecuta `python3 server.py` en segundo plano.
3. Espera brevemente.
4. Abre Google Chrome en modo app apuntando a `http://127.0.0.1:7788`.

El resultado es una ventana sin barra de navegador, redimensionable y movible como si fuese una app nativa.

## Como funciona

El backend mantiene un diccionario global llamado `agent_states` con el estado de cada agente:

```python
agent_states = {
    "hermes": {"status": "idle", "last_line": "", "activity": 0, "instances": 1},
    "claude": {"status": "idle", "last_line": "", "activity": 0, "instances": 1},
    "codex":  {"status": "idle", "last_line": "", "activity": 0, "instances": 1},
}
```

Cada entrada contiene:

- `status`: estado visual del agente.
- `last_line`: ultima linea o mensaje relevante detectado.
- `activity`: timestamp de la ultima actividad.
- `instances`: cantidad de procesos detectados para ese agente.

El servidor ejecuta varias tareas asincronas:

- `tail_log(...)`: sigue logs de Hermes y Codex.
- `poll_claude()`: inspecciona archivos JSONL de Claude Code.
- `poll_instances()`: cuenta sesiones de agente vivas inspeccionando procesos locales.
- `decay_status()`: degrada estados con el paso del tiempo.
- `broadcast()`: envia el estado actual a todos los clientes WebSocket conectados.

El frontend recibe ese JSON, crea o elimina robots segun el numero de instancias, actualiza estados y muestra la ultima linea detectada como burbuja sobre el robot principal de cada agente.

## Agentes soportados

Los agentes configurados actualmente son:

| Agente | ID interno | Color UI | Fuente de actividad | Patron de proceso |
| --- | --- | --- | --- | --- |
| Hermes | `hermes` | Verde neon | `~/.hermes/logs/agent.log` | CLI en terminal: `venv/bin/hermes`, `hermes` |
| Claude Code | `claude` | Naranja | `~/.claude/projects/**/*.jsonl` | CLI en terminal: `opt/homebrew/bin/claude`, `claude`, `claude.exe` |
| Codex | `codex` | Violeta | `~/.codex/log/codex-tui.log` | CLI en terminal: `local/bin/codex`, `codex`, `codex.exe` |
| Ollama | `ollama` | Azul cian | `~/Library/Logs/Ollama/server.log`, `~/.ollama/logs/server.log`, `%LOCALAPPDATA%/Ollama/server.log` | `ollama`, `ollama.exe` |

Estas fuentes se definen en `server.py`:

```python
LOG_SOURCES = {
    "hermes": Path.home() / ".hermes/logs/agent.log",
    "claude": Path.home() / ".claude/projects",
    "codex":  Path.home() / ".codex/log/codex-tui.log",
    "ollama": first_existing(...),
}
```

Y los patrones de proceso se definen aqui:

```python
PROCESS_PATTERNS = {
    "hermes": {"posix": {"commands": [...], "contains": [...], "require_tty": True}, ...},
    "claude": {"posix": {"commands": [...], "contains": [...], "require_tty": True}, ...},
    "codex":  {"posix": {"commands": [...], "contains": [...], "require_tty": True}, ...},
    "ollama": {"posix": {"commands": [...], "contains": [...], "require_tty": False}, ...},
}
```

## Estados del agente

El dashboard usa tres estados principales:

### `idle`

Estado de reposo. El robot se muestra mas tenue, se mueve despacio y no emite actividad destacada.

### `working`

Estado activo. Se asigna cuando el backend detecta una linea nueva en un log o un mensaje nuevo en Claude. Visualmente:

- el robot se ilumina mas;
- aumenta su velocidad;
- emite particulas;
- puede mostrar una burbuja con texto;
- puede conectarse con otros robots activos mediante haces de luz.

### `thinking`

Estado intermedio. Se asigna automaticamente cuando un agente estuvo `working`, pero no tuvo actividad nueva durante unos segundos.

La logica actual de degradacion es:

```text
working  -> thinking despues de 4 segundos sin actividad
thinking -> idle     despues de 12 segundos sin actividad
```

Esta logica vive en `decay_status()` dentro de `server.py`.

## Servidor backend

El backend esta implementado con FastAPI.

Endpoints:

| Metodo | Ruta | Descripcion |
| --- | --- | --- |
| `GET` | `/` | Devuelve `index.html` como HTML |
| WebSocket | `/ws` | Envia el estado de agentes en tiempo real |

Arranque:

```python
uvicorn.run(app, host="127.0.0.1", port=7788, log_level="warning")
```

El servidor solo escucha en localhost. Esto evita exponer el dashboard directamente a la red local.

### Tareas asincronas

El ciclo de vida de FastAPI crea las tareas al arrancar:

```python
@asynccontextmanager
async def lifespan(_app):
    asyncio.create_task(tail_log(LOG_SOURCES["hermes"], "hermes"))
    asyncio.create_task(tail_log(LOG_SOURCES["codex"], "codex"))
    asyncio.create_task(poll_claude())
    asyncio.create_task(poll_instances())
    asyncio.create_task(decay_status())
    yield
```

Estas tareas corren de forma continua mientras el servidor esta vivo.

### Lectura de logs

Para Hermes y Codex se usa una funcion tipo `tail -f`:

```python
async def tail_log(path: Path, name: str):
    ...
```

La funcion:

1. Comprueba si el archivo existe.
2. Abre el archivo.
3. Se posiciona al final.
4. Lee nuevas lineas.
5. Actualiza `last_line`, `status` y `activity`.
6. Emite el nuevo estado por WebSocket.

Importante: al posicionarse al final del archivo, el dashboard solo reacciona a lineas nuevas desde que el servidor esta corriendo.

### Lectura de Claude Code

Claude se trata de forma diferente. En vez de hacer tail de un unico archivo, busca el archivo JSONL mas reciente bajo:

```text
~/.claude/projects
```

Luego inspecciona mensajes del asistente y toma contenido textual. El texto se recorta a 120 caracteres para evitar burbujas demasiado largas.

## Frontend Canvas

La interfaz esta escrita en JavaScript puro dentro de `index.html`.

No usa React, Vue, Svelte, bundlers, CSS externo ni assets. Todo se dibuja con Canvas 2D.

Partes principales:

- setup del canvas;
- dibujo de la sala;
- ventanas del fondo con lineas tipo codigo;
- suelo con perspectiva;
- particulas;
- clase `Robot`;
- haces de conexion entre robots activos;
- pool de robots sincronizado con el WebSocket;
- bucle de render con `requestAnimationFrame`.

### Sala de control

La sala usa una perspectiva falsa basada en coordenadas de mundo:

```javascript
function worldToScreen(wx, wz) {
  // wx: -1..1 izquierda-derecha
  // wz: 0..1 fondo-frente
}
```

Cada robot tiene una posicion `wx` y `wz`. La funcion transforma esas coordenadas en posicion de pantalla y escala visual. Asi, los robots del fondo se ven mas pequenos y los del frente mas grandes.

### Robots

Cada robot se representa con la clase:

```javascript
class Robot {
  constructor(uid, agentId, instanceIdx) { ... }
}
```

La configuracion visual base esta en:

```javascript
const CONFIGS = {
  hermes: { name:'Hermes',      color:'#00ff88', glow:'rgba(0,255,136,',   shade:'#00cc70' },
  claude: { name:'Claude Code', color:'#ff6b35', glow:'rgba(255,107,53,',  shade:'#cc5528' },
  codex:  { name:'Codex',       color:'#a78bfa', glow:'rgba(167,139,250,', shade:'#8b6fd4' },
};
```

Cada robot:

- se mueve de forma autonoma;
- cambia velocidad segun estado;
- tiene ojos, cuerpo, antena y panel de pecho;
- muestra nombre y estado;
- emite particulas cuando trabaja;
- muestra burbujas cuando llega una nueva linea de actividad.

### Multiples instancias

El backend envia `instances` para cada agente. El frontend crea tantos robots como instancias detectadas:

```javascript
function syncRobots(agentId, state) {
  const needed = state.instances || 1;
  ...
}
```

Si hay mas de una instancia, el nombre visual se numera:

```text
Codex
Codex #2
Codex #3
```

Solo la primera instancia recibe la burbuja con `last_line`; las demas reflejan el estado general.

## WebSocket

El cliente conecta a:

```javascript
const ws = new WebSocket('ws://127.0.0.1:7788/ws');
```

Cuando recibe datos:

```javascript
ws.onmessage = e => {
  const data = JSON.parse(e.data);
  for (const [id, state] of Object.entries(data)) {
    syncRobots(id, state);
  }
};
```

Si la conexion se cierra, intenta reconectar cada 2 segundos:

```javascript
ws.onclose = () => setTimeout(connect, 2000);
```

El payload enviado por el servidor tiene esta forma:

```json
{
  "hermes": {
    "status": "idle",
    "last_line": "",
    "activity": 0,
    "instances": 1
  },
  "claude": {
    "status": "working",
    "last_line": "Texto reciente del asistente",
    "activity": 1710000000.0,
    "instances": 1
  },
  "codex": {
    "status": "thinking",
    "last_line": "Ultima linea detectada",
    "activity": 1710000000.0,
    "instances": 2
  }
}
```

## Script de ventana flotante

`widget.sh` automatiza el uso en macOS:

```bash
./widget.sh
```

Contenido funcional:

- usa `lsof -ti:7788` para saber si el puerto esta ocupado;
- si el puerto esta libre, arranca `python3 server.py`;
- usa `open -na "Google Chrome" --args --app=...` para abrir Chrome sin barra de navegador;
- define tamano inicial de ventana `1200x750`;
- define posicion inicial `80,80`;
- deshabilita extensiones para esa ventana.

Si no tienes Google Chrome instalado, puedes ejecutar el servidor manualmente y abrir la URL en otro navegador.

## Configuracion

Actualmente la configuracion esta codificada en los archivos fuente.

### Cambiar puerto

Hay que actualizar dos sitios:

En `server.py`:

```python
uvicorn.run(app, host="127.0.0.1", port=7788, log_level="warning")
```

En `index.html`:

```javascript
const ws = new WebSocket('ws://127.0.0.1:7788/ws');
```

Y si usas `widget.sh`, tambien:

```bash
lsof -ti:7788
--app=http://127.0.0.1:7788
```

### Cambiar fuentes de logs

Edita `LOG_SOURCES` en `server.py`:

```python
LOG_SOURCES = {
    "hermes": Path.home() / ".hermes/logs/agent.log",
    "claude": Path.home() / ".claude/projects",
    "codex":  Path.home() / ".codex/log/codex-tui.log",
}
```

### Cambiar patrones de procesos

Edita `PROCESS_PATTERNS` en `server.py`:

```python
PROCESS_PATTERNS = {
    "hermes": {"posix": ["venv/bin/hermes", "hermes"], "windows": ["hermes.exe", "hermes"]},
    "claude": {"posix": ["opt/homebrew/bin/claude", "claude"], "windows": ["claude.exe", "claude"]},
    "codex":  {"posix": ["local/bin/codex", "codex"], "windows": ["codex.exe", "codex"]},
    "ollama": {"posix": ["ollama"], "windows": ["ollama.exe", "ollama"]},
}
```

En macOS y Linux los patrones se buscan dentro de la salida de:

```bash
ps aux
```

En Windows se usa:

```powershell
tasklist /FO CSV /NH
```

Para Hermes, Claude Code y Codex en macOS/Linux se exige TTY de terminal, por lo que no se cuentan apps de escritorio ni helpers de fondo. Ollama permite procesos sin TTY porque normalmente corre como servicio local.

## Personalizacion

### Anadir un agente nuevo

Para anadir un agente nuevo hay que tocar backend y frontend.

En `server.py`:

1. Agrega una entrada en `LOG_SOURCES`.
2. Agrega una entrada en `PROCESS_PATTERNS`.
3. Agrega una entrada inicial en `agent_states`.
4. Crea una tarea de lectura o polling en `lifespan()`.

Ejemplo:

```python
LOG_SOURCES["nuevo"] = Path.home() / ".nuevo/logs/agent.log"
PROCESS_PATTERNS["nuevo"] = "nuevo-agent"
agent_states["nuevo"] = {"status": "idle", "last_line": "", "activity": 0, "instances": 1}
```

En `index.html`, agrega una configuracion visual:

```javascript
const CONFIGS = {
  ...
  nuevo: { name:'Nuevo', color:'#00d5ff', glow:'rgba(0,213,255,', shade:'#0099bb' },
};
```

El ID debe coincidir exactamente entre backend y frontend.

### Cambiar colores

Los colores de cada agente estan en `CONFIGS` dentro de `index.html`.

Ejemplo:

```javascript
codex: {
  name:'Codex',
  color:'#a78bfa',
  glow:'rgba(167,139,250,',
  shade:'#8b6fd4'
}
```

### Cambiar intensidad visual

Algunos puntos utiles:

- Velocidad por estado: getter `worldSpeed`.
- Particulas: metodo `emitParticles`.
- Brillo: bloque `glow` dentro de `draw()`.
- Burbujas: metodo `drawBubble`.
- Haces entre agentes: funcion `drawBeams`.
- Fondo y sala: `drawRoom`, `drawWindows`, `drawFloor`.

### Cambiar duracion de estados

Edita `decay_status()` en `server.py`:

```python
if s["status"] == "working" and now - s["activity"] > 4:
    s["status"] = "thinking"
elif s["status"] == "thinking" and now - s["activity"] > 12:
    s["status"] = "idle"
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'fastapi'`

Instala las dependencias:

```bash
pip install fastapi uvicorn
```

Si usas entorno virtual, asegurate de activarlo antes:

```bash
source .venv/bin/activate
```

### El puerto `7788` ya esta ocupado

Comprueba que proceso lo usa:

```bash
lsof -i :7788
```

Puedes cerrar ese proceso o cambiar el puerto en `server.py`, `index.html` y `widget.sh`.

### La pagina abre pero no se actualiza

Comprueba:

- que el servidor sigue corriendo;
- que el navegador puede conectar a `ws://127.0.0.1:7788/ws`;
- que los logs existen;
- que hay nuevas lineas en los logs despues de arrancar el servidor.

### No aparece actividad de Hermes o Codex

`tail_log()` se posiciona al final del archivo. Si el log ya tenia contenido antes de arrancar el servidor, no lo mostrara como actividad nueva. Genera actividad nueva en el agente y observa si cambia el dashboard.

Tambien verifica que existan estas rutas:

```text
~/.hermes/logs/agent.log
~/.codex/log/codex-tui.log
```

### No aparece actividad de Claude Code

Claude se lee desde:

```text
~/.claude/projects
```

El servidor busca archivos `*.jsonl`, toma el mas reciente y extrae mensajes con:

```json
{
  "message": {
    "role": "assistant",
    "content": "..."
  }
}
```

Si el formato cambia, puede que `get_latest_claude_line()` necesite actualizarse.

### El contador de instancias parece incorrecto

El contador usa:

```bash
ps aux
```

Despues filtra las lineas que contienen el patron configurado en `PROCESS_PATTERNS` y solo cuenta procesos asociados a una TTY que empiece por `s`. Si el contador parece incorrecto, ajusta `PROCESS_PATTERNS` para que el patron coincida con el binario real que quieres contar.

### `widget.sh` no abre Chrome

Comprueba que Google Chrome existe con ese nombre de app:

```bash
open -na "Google Chrome"
```

Si usas otro navegador, ejecuta `python3 server.py` y abre manualmente:

```text
http://127.0.0.1:7788
```

### Permiso denegado al ejecutar `widget.sh`

Hazlo ejecutable:

```bash
chmod +x widget.sh
```

## Desarrollo

### Ejecutar en modo servidor

```bash
python3 server.py
```

### Comprobar sintaxis Python

```bash
python3 -m py_compile server.py
```

### Revisar archivos del proyecto

```bash
find . -maxdepth 2 -type f
```

### Flujo recomendado para cambios

1. Modifica `server.py` si el cambio afecta datos, agentes, procesos o WebSocket.
2. Modifica `index.html` si el cambio afecta visualizacion, animacion o comportamiento del cliente.
3. Reinicia `server.py`.
4. Recarga el navegador.
5. Genera actividad real en alguno de los agentes.
6. Verifica que el robot cambia de estado y vuelve a reposo con el tiempo.

## Seguridad y privacidad

El dashboard lee informacion local de logs de agentes. Eso puede incluir texto sensible generado por sesiones de trabajo.

Consideraciones:

- El servidor escucha solo en `127.0.0.1`.
- No envia datos a servicios externos.
- No guarda historico propio.
- Emite por WebSocket la ultima linea detectada para cada agente.
- Cualquier navegador local conectado al WebSocket puede ver esos mensajes.

No cambies el host a `0.0.0.0` salvo que entiendas el riesgo. Si se expone en red, otros dispositivos podrian acceder al dashboard y ver fragmentos de actividad.

## Limitaciones conocidas

- No hay archivo de dependencias versionado.
- No hay autenticacion.
- No hay tests automatizados.
- El puerto esta hardcodeado.
- El cliente WebSocket usa una URL fija.
- La configuracion de agentes esta repartida entre backend y frontend.
- Los logs de Hermes y Codex se leen solo si el archivo existe al arrancar la tarea.
- La deteccion de instancias mediante busqueda textual sobre `ps aux` o `tasklist` puede producir falsos positivos si los patrones son demasiado amplios.
- Claude depende del formato actual de los archivos JSONL en `~/.claude/projects`.
- `widget.sh` esta orientado a macOS y `widget.ps1` cubre Windows con Chrome o navegador predeterminado.

## Roadmap sugerido

Ideas razonables para evolucionar el proyecto:

- Crear `requirements.txt` o `pyproject.toml`.
- Mover agentes, colores, rutas y patrones a un archivo de configuracion.
- Exponer el puerto mediante variable de entorno.
- Servir la URL WebSocket de forma relativa al host actual.
- Anadir endpoint `/health`.
- Mostrar estado de conexion en la UI.
- Anadir modo debug con JSON visible.
- Guardar un pequeno historial de ultimos mensajes.
- Permitir ocultar o mostrar agentes.
- Anadir tests unitarios para parsing de logs y estados.
- Anadir soporte para logs que aparecen despues de arrancar el servidor.
- Evitar falsos positivos en conteo de procesos usando una estrategia mas estricta.

## Resumen tecnico

`agent-dashboard` es una aplicacion local minimalista pero expresiva:

- Python se encarga de observar el sistema.
- FastAPI mantiene el canal HTTP/WebSocket.
- JavaScript dibuja una interfaz viva en Canvas.
- Los logs y procesos locales son la fuente de verdad.
- El navegador solo refleja el estado que el backend calcula.

Es un buen punto de partida para una sala de control personal de agentes, especialmente si se quiere visualizar actividad de varias herramientas de IA sin depender de servicios externos ni montar una arquitectura pesada.
