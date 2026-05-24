import asyncio
import json
import os
import platform
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

def first_existing(*paths: Path):
    for path in paths:
        if path and path.exists():
            return path
    return paths[0] if paths else None


HOME = Path.home()
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", HOME))

LOG_SOURCES = {
    "hermes": HOME / ".hermes/logs/agent.log",
    "claude": HOME / ".claude/projects",
    "codex":  HOME / ".codex/log/codex-tui.log",
    "ollama": first_existing(
        HOME / "Library/Logs/Ollama/server.log",
        HOME / ".ollama/logs/server.log",
        LOCALAPPDATA / "Ollama/server.log",
    ),
}

PROCESS_PATTERNS = {
    "hermes": {
        "posix": {"commands": ["hermes"], "contains": ["venv/bin/hermes"], "require_tty": True},
        "windows": {"commands": ["hermes.exe", "hermes"]},
    },
    "claude": {
        "posix": {"commands": ["claude"], "contains": ["opt/homebrew/bin/claude"], "require_tty": True},
        "windows": {"commands": ["claude.exe", "claude"]},
    },
    "codex": {
        "posix": {"commands": ["codex"], "contains": ["local/bin/codex"], "require_tty": True},
        "windows": {"commands": ["codex.exe", "codex"]},
    },
    "ollama": {
        "posix": {"commands": ["ollama"], "contains": ["Ollama.app", "ollama serve"], "require_tty": False},
        "windows": {"commands": ["ollama.exe", "ollama"]},
    },
}

agent_states = {
    "hermes": {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
    "claude": {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
    "codex":  {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
    "ollama": {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
}

clients: set = set()


def active_patterns(pattern_config: dict) -> list[str]:
    key = "windows" if platform.system().lower().startswith("win") else "posix"
    return pattern_config.get(key, {})


def matches_process(command: str, args: str, rules: dict) -> bool:
    command_name = Path(command).name.lower()
    commands = [c.lower() for c in rules.get("commands", [])]
    contains = [c.lower() for c in rules.get("contains", [])]
    haystack = f"{command} {args}".lower()
    return command_name in commands or any(fragment in haystack for fragment in contains)


def count_instances(pattern_config: dict) -> int:
    """Count agent processes on macOS/Linux and Windows."""
    rules = active_patterns(pattern_config)
    if not rules:
        return 0
    try:
        if platform.system().lower().startswith("win"):
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                shell=False,
            )
            count = 0
            commands = [c.lower() for c in rules.get("commands", [])]
            for line in result.stdout.splitlines():
                image_name = line.split(",", 1)[0].strip().strip('"').lower()
                if image_name in commands:
                    count += 1
            return count
        else:
            result = subprocess.run(
                ["ps", "-axo", "pid=,tty=,comm=,args="],
                capture_output=True,
                text=True,
            )
        count = 0
        for line in result.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            _pid, tty, command, args = parts
            if rules.get("require_tty") and tty == "??":
                continue
            if matches_process(command, args, rules):
                count += 1
        return count
    except Exception:
        return 0


def get_latest_claude_line() -> str:
    try:
        files = sorted(
            (Path.home() / ".claude/projects").rglob("*.jsonl"),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        if not files:
            return ""
        for raw in reversed(files[0].read_text().splitlines()):
            try:
                data = json.loads(raw)
                msg = data.get("message", {})
                if msg.get("role") == "assistant":
                    c = msg.get("content", "")
                    if isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get("type") == "text":
                                return b["text"][:120]
                    elif isinstance(c, str):
                        return c[:120]
            except Exception:
                continue
    except Exception:
        pass
    return ""


async def tail_log(path: Path, name: str):
    if not path or not path.exists():
        return
    with open(path) as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                text = line.strip()[-120:]
                if text:
                    agent_states[name]["last_line"] = text
                    agent_states[name]["status"] = "working"
                    agent_states[name]["activity"] = time.time()
                    await broadcast()
            else:
                await asyncio.sleep(0.25)


async def poll_claude():
    while True:
        line = get_latest_claude_line()
        if line and line != agent_states["claude"]["last_line"]:
            agent_states["claude"]["last_line"] = line
            agent_states["claude"]["status"] = "working"
            agent_states["claude"]["activity"] = time.time()
            await broadcast()
        await asyncio.sleep(1)


async def poll_instances():
    while True:
        changed = False
        for name, pattern in PROCESS_PATTERNS.items():
            n = count_instances(pattern)
            if n != agent_states[name]["instances"]:
                agent_states[name]["instances"] = n
                changed = True
        if changed:
            await broadcast()
        await asyncio.sleep(4)


async def decay_status():
    while True:
        now = time.time()
        changed = False
        for name, s in agent_states.items():
            if s["status"] == "working" and now - s["activity"] > 4:
                agent_states[name]["status"] = "thinking"
                changed = True
            elif s["status"] == "thinking" and now - s["activity"] > 12:
                agent_states[name]["status"] = "idle"
                changed = True
        if changed:
            await broadcast()
        await asyncio.sleep(1)


async def broadcast():
    if not clients:
        return
    payload = json.dumps(agent_states)
    dead = set()
    for ws in clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


@asynccontextmanager
async def lifespan(_app):
    asyncio.create_task(tail_log(LOG_SOURCES["hermes"], "hermes"))
    asyncio.create_task(tail_log(LOG_SOURCES["codex"], "codex"))
    asyncio.create_task(tail_log(LOG_SOURCES["ollama"], "ollama"))
    asyncio.create_task(poll_claude())
    asyncio.create_task(poll_instances())
    asyncio.create_task(decay_status())
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/vendor", StaticFiles(directory=Path(__file__).parent / "vendor"), name="vendor")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    await websocket.send_text(json.dumps(agent_states))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.discard(websocket)


@app.get("/")
async def root():
    return HTMLResponse((Path(__file__).parent / "index.html").read_text())


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=7788, log_level="warning")
