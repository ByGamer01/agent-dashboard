import asyncio
import json
import os
import platform
import re
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn


PORT = int(os.environ.get("DASHBOARD_PORT", "7788"))
HOME = Path.home()
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", HOME))


def first_existing(*paths: Path):
    for path in paths:
        if path and path.exists():
            return path
    return paths[0] if paths else None


LOG_SOURCES = {
    "hermes": HOME / ".hermes/logs/agent.log",
    "claude": HOME / ".claude/projects",
    "codex": HOME / ".codex/log/codex-tui.log",
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
    "codex": {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
    "ollama": {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
}

clients: set = set()
shutdown_event = asyncio.Event()


def active_rules(pattern_config: dict) -> dict:
    key = "windows" if platform.system().lower().startswith("win") else "posix"
    return pattern_config.get(key, {})


def matches_process(command: str, args: str, rules: dict) -> bool:
    command_name = Path(command).name.lower()
    commands = [c.lower() for c in rules.get("commands", [])]
    contains = [c.lower() for c in rules.get("contains", [])]
    haystack = f"{command} {args}".lower()
    return command_name in commands or any(fragment in haystack for fragment in contains)


def count_instances(pattern_config: dict) -> int:
    """Count agent processes on macOS/Linux and Windows.

    Terminal agents require a real TTY on POSIX so desktop apps such as Claude
    Desktop and helper processes are not counted as Claude Code sessions.
    """
    rules = active_rules(pattern_config)
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
            commands = [c.lower() for c in rules.get("commands", [])]
            count = 0
            for line in result.stdout.splitlines():
                image_name = line.split(",", 1)[0].strip().strip('"').lower()
                if image_name in commands:
                    count += 1
            return count

        result = subprocess.run(
            ["ps", "-axo", "pid=,tty=,comm=,args="],
            capture_output=True,
            text=True,
        )
        terminal_ttys = set()
        background_count = 0
        for line in result.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            _pid, tty, command, args = parts
            if rules.get("require_tty") and tty == "??":
                continue
            if not matches_process(command, args, rules):
                continue
            if rules.get("require_tty"):
                terminal_ttys.add(tty)
            else:
                background_count += 1
        return len(terminal_ttys) if rules.get("require_tty") else background_count
    except Exception:
        return 0


def get_latest_claude_line() -> str:
    try:
        projects_dir = HOME / ".claude/projects"
        if not projects_dir.exists():
            return ""
        files = sorted(
            projects_dir.rglob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return ""
        for raw in reversed(files[0].read_text().splitlines()):
            try:
                data = json.loads(raw)
                msg = data.get("message", {})
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                return block["text"][:120]
                    elif isinstance(content, str):
                        return content[:120]
            except Exception:
                continue
    except Exception:
        pass
    return ""


def extract_human_readable(line: str):
    text = line.strip()
    if not text:
        return (None, False)

    match = re.search(r"msg='([^']+)'", text) or re.search(r'msg="([^"]+)"', text)
    if match:
        msg = match.group(1)
        if len(msg) > 80:
            msg = msg[:77] + "..."
        return (f"MSG {msg}", True)

    match = re.search(r"Turn ended: reason=(\w+)", text)
    if match:
        labels = {
            "text_response": "Response sent",
            "tool_call": "Ran tool",
            "error": "Agent error",
            "max_turns": "Turn limit reached",
            "interrupted": "Interrupted",
        }
        reason = match.group(1)
        return (labels.get(reason, reason), False)

    match = re.search(r"tool_executor: tool (\w+) completed", text)
    if match:
        tool_name = match.group(1)
        if tool_name in (
            "skills_list",
            "skill_view",
            "memory",
            "session_search",
            "hindsight_recall",
            "hindsight_retain",
            "hindsight_reflect",
            "todo",
            "process",
            "send_message",
        ):
            return (None, False)
        if len(tool_name) > 16:
            return (None, False)
        return (f"Ran {tool_name}", False)

    if " ERROR " in text or " CRITICAL " in text:
        parts = text.split(" ERROR ", 1)
        if len(parts) < 2:
            parts = text.split(" CRITICAL ", 1)
        if len(parts) >= 2:
            err = parts[1].strip()
            if len(err) > 80:
                err = err[:77] + "..."
            return (err, True)

    lowered = text.lower()
    if "agent initialized" in lowered:
        return ("Agent started", True)
    if "shutting down" in lowered or "shutdown" in lowered:
        return ("Shutting down", True)

    # Ollama logs are mostly plain server events; keep short useful lines.
    if "ollama" in lowered or "model" in lowered or "loaded" in lowered:
        return (text[-120:], False)

    return (None, False)


async def tail_log(path: Path, name: str):
    if not path or not path.exists():
        return
    with open(path, encoding="utf-8", errors="ignore") as f:
        f.seek(0, 2)
        while not shutdown_event.is_set():
            line = f.readline()
            if line:
                readable, is_activity = extract_human_readable(line)
                if readable and readable != agent_states[name]["last_line"]:
                    agent_states[name]["last_line"] = readable
                    agent_states[name]["activity"] = time.time()
                    if is_activity:
                        agent_states[name]["status"] = "working"
                    await broadcast()
            else:
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=0.25)
                except asyncio.TimeoutError:
                    pass


async def poll_claude():
    while not shutdown_event.is_set():
        if count_instances(PROCESS_PATTERNS["claude"]) > 0:
            line = get_latest_claude_line()
            if line and line != agent_states["claude"]["last_line"]:
                agent_states["claude"]["last_line"] = line
                agent_states["claude"]["status"] = "working"
                agent_states["claude"]["activity"] = time.time()
                await broadcast()
        elif agent_states["claude"]["last_line"]:
            agent_states["claude"]["last_line"] = ""
            agent_states["claude"]["status"] = "idle"
            agent_states["claude"]["activity"] = 0
            await broadcast()
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass


async def poll_instances():
    while not shutdown_event.is_set():
        changed = False
        for name, pattern in PROCESS_PATTERNS.items():
            instances = count_instances(pattern)
            if instances != agent_states[name]["instances"]:
                agent_states[name]["instances"] = instances
                changed = True
        if changed:
            await broadcast()
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass


async def decay_status():
    while not shutdown_event.is_set():
        now = time.time()
        changed = False
        for name, state in agent_states.items():
            if state["status"] == "working" and now - state["activity"] > 8:
                agent_states[name]["status"] = "idle"
                changed = True
        if changed:
            await broadcast()
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass


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
    if dead:
        clients.difference_update(dead)


@asynccontextmanager
async def lifespan(_app):
    tasks = [
        asyncio.create_task(tail_log(LOG_SOURCES["hermes"], "hermes")),
        asyncio.create_task(tail_log(LOG_SOURCES["codex"], "codex")),
        asyncio.create_task(tail_log(LOG_SOURCES["ollama"], "ollama")),
        asyncio.create_task(poll_claude()),
        asyncio.create_task(poll_instances()),
        asyncio.create_task(decay_status()),
    ]
    yield
    shutdown_event.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


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


@app.get("/health")
async def health():
    return {"status": "ok", "port": PORT, "clients": len(clients)}


@app.get("/")
async def root():
    return HTMLResponse((Path(__file__).parent / "index.html").read_text())


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
