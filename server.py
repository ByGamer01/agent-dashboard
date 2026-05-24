import asyncio
import json
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

LOG_SOURCES = {
    "hermes": Path.home() / ".hermes/logs/agent.log",
    "claude": Path.home() / ".claude/projects",
    "codex":  Path.home() / ".codex/log/codex-tui.log",
}

# Match only foreground terminal sessions, not subprocesses/background daemons
PROCESS_PATTERNS = {
    "hermes": "venv/bin/hermes",
    "claude": "opt/homebrew/bin/claude",
    "codex":  "local/bin/codex",
}

agent_states = {
    "hermes": {"status": "idle", "last_line": "", "activity": 0, "instances": 1},
    "claude": {"status": "idle", "last_line": "", "activity": 0, "instances": 1},
    "codex":  {"status": "idle", "last_line": "", "activity": 0, "instances": 1},
}

clients: set = set()


def count_instances(cmd_pattern: str) -> int:
    """Count only foreground terminal sessions (tty s00X), not background daemons."""
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        count = 0
        for line in result.stdout.splitlines():
            if cmd_pattern not in line:
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            tty = parts[6]  # TTY column
            # Only count sessions attached to a terminal (s000, s001, etc.)
            if tty.startswith("s"):
                count += 1
        return max(1, count)
    except Exception:
        return 1


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
