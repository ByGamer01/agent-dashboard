import asyncio
import json
import os
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

LOG_SOURCES = {
    "hermes": Path.home() / ".hermes/logs/agent.log",
    "codex":  Path.home() / ".codex/log/codex-tui.log",
}

# Match only foreground terminal sessions, not subprocesses/background daemons.
# Use the process binary name — works across Linux and macOS via ps aux.
PROCESS_PATTERNS = {
    "hermes": "hermes",
    "claude": "claude",
    "codex":  "codex",
}

agent_states = {
    "hermes": {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
    "claude": {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
    "codex":  {"status": "idle", "last_line": "", "activity": 0, "instances": 0},
}

clients: set = set()
shutdown_event = asyncio.Event()


def count_instances(cmd_pattern: str) -> int:
    """Count unique terminal sessions running the given process.
    Counts each unique TTY once, so multiple processes spawned by the
    same session (e.g. hermes's python + node + gateway) count as 1."""
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        ttys = set()
        for line in result.stdout.splitlines():
            if cmd_pattern not in line:
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            tty = parts[6]  # TTY column
            if tty and tty[0] != "?":  # attached to a terminal
                ttys.add(tty)
        return len(ttys)
    except Exception:
        return 0


def get_latest_claude_line() -> str:
    try:
        projects_dir = Path.home() / ".claude/projects"
        if not projects_dir.exists():
            return ""
        files = sorted(
            projects_dir.rglob("*.jsonl"),
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


# ─── Log line filter: extract human-readable status from raw agent logs ─────
# Returns (text, is_user_activity).
# is_user_activity=True  → bot goes to workstation (user asked something)
# is_user_activity=False → just updates the speech bubble (passive status)

def extract_human_readable(line: str) -> tuple[str | None, bool]:
    """Extract a human-readable status from a raw agent log line.
    Returns (None, False) for internal/debug noise.
    Returns (text, True) for user-facing activity (conversation turns, errors).
    Returns (text, False) for passive updates (tool completions, status).
    """
    text = line.strip()
    if not text:
        return (None, False)

    # 1. conversation turn → user activity! Shows what the user asked
    m = re.search(r"msg='([^']+)'", text)
    if not m:
        m = re.search(r'msg="([^"]+)"', text)
    if m:
        msg = m.group(1)
        if len(msg) > 80:
            msg = msg[:77] + "..."
        return (f"📩 {msg}", True)

    # 2. Turn ended → passive status update
    m = re.search(r"Turn ended: reason=(\w+)", text)
    if m:
        reason = m.group(1)
        labels = {
            "text_response": "✅ Response sent",
            "tool_call":    "🔧 Ran tool",
            "error":        "⚠️ Agent error",
            "max_turns":    "⏱ Turn limit reached",
            "interrupted":  "⏸ Interrupted",
        }
        return (labels.get(reason, f"✅ {reason}"), False)

    # 3. Tool execution — PASSIVE, don't trigger working
    # Only show file/tool operations, skip internal plumbing
    m = re.search(r"tool_executor: tool (\w+) completed", text)
    if m:
        tool_name = m.group(1)
        # Skip internal/housekeeping tools — not user-facing
        if tool_name in ("skills_list", "skill_view", "memory", "session_search",
                         "hindsight_recall", "hindsight_retain", "hindsight_reflect",
                         "todo", "process", "send_message"):
            return (None, False)
        if len(tool_name) > 16:
            return (None, False)
        return (f"🔧 Ran {tool_name}", False)

    # 4. Error lines — user-facing, but only if there's actual error content
    if " ERROR " in text or " CRITICAL " in text:
        parts = text.split(" ERROR ", 1)
        if len(parts) < 2:
            parts = text.split(" CRITICAL ", 1)
        if len(parts) >= 2:
            err = parts[1].strip()
            if len(err) > 80:
                err = err[:77] + "..."
            return (f"❌ {err}", True)

    # 5. Key lifecycle events — passive
    if "agent initialized" in text.lower():
        return ("🚀 Agent started", True)
    if "shutting down" in text.lower() or "shutdown" in text.lower():
        return ("🛑 Shutting down", True)

    # Everything else is internal noise → skip
    return (None, False)


async def tail_log(path: Path, name: str):
    """Tail an agent log file — user conversations trigger 'working', tools don't."""
    if not path or not path.exists():
        return
    with open(path) as f:
        f.seek(0, 2)  # start at end
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
        if count_instances("claude") > 0:
            line = get_latest_claude_line()
            if line and line != agent_states["claude"]["last_line"]:
                agent_states["claude"]["last_line"] = line
                agent_states["claude"]["status"] = "working"
                agent_states["claude"]["activity"] = time.time()
                await broadcast()
        else:
            # Clear stale data when claude isn't running
            if agent_states["claude"]["last_line"]:
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
            n = count_instances(pattern)
            if n != agent_states[name]["instances"]:
                agent_states[name]["instances"] = n
                changed = True
        if changed:
            await broadcast()
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass


async def decay_status():
    """Decay working→idle after 8s of inactivity (no fake 'thinking' state)."""
    while not shutdown_event.is_set():
        now = time.time()
        changed = False
        for name, s in agent_states.items():
            if s["status"] == "working" and now - s["activity"] > 8:
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
        asyncio.create_task(poll_claude()),
        asyncio.create_task(poll_instances()),
        asyncio.create_task(decay_status()),
    ]
    yield
    shutdown_event.set()
    for t in tasks:
        t.cancel()
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
