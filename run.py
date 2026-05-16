"""
run.py  —  EchoForge V3 Launcher

Starts both required processes from a single terminal:
  • engine/orchestrator.py  — pipeline daemon
  • bot/main.py             — Telegram dashboard

Both processes run as children of this script.  Logs from each are
prefixed with [ORCH] or [BOT] so you can tell them apart in one terminal.

USAGE:
    python run.py

STOP:
    Ctrl+C  — gracefully terminates both children before exiting.
"""

import os
import signal
import subprocess
import sys
import threading
import time

ROOT_DIR   = os.path.dirname(os.path.abspath(__file__))
ORCH_PATH  = os.path.join(ROOT_DIR, "engine", "orchestrator.py")
BOT_PATH   = os.path.join(ROOT_DIR, "bot",    "main.py")
PYTHON     = sys.executable   # same interpreter that's running this file


# ─── Colour prefixes (optional, disabled on Windows if not supported) ─────────

def _supports_colour() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and os.name != "nt"

_CYAN   = "\033[96m" if _supports_colour() else ""
_YELLOW = "\033[93m" if _supports_colour() else ""
_RED    = "\033[91m" if _supports_colour() else ""
_RESET  = "\033[0m"  if _supports_colour() else ""

ORCH_PREFIX = f"{_CYAN}[ORCH]{_RESET} "
BOT_PREFIX  = f"{_YELLOW}[BOT ]{_RESET} "


# ─── Stream reader — pipes child stdout/stderr to our console ─────────────────

def _stream(pipe, prefix: str) -> None:
    """Read lines from *pipe* and print them with *prefix*. Runs in a thread."""
    try:
        for raw in iter(pipe.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                print(f"{prefix}{line}", flush=True)
    except Exception:
        pass


# ─── Process launcher ─────────────────────────────────────────────────────────

def _start(script: str, prefix: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        [PYTHON, "-u", script],   # -u = unbuffered so logs appear instantly
        cwd=ROOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge stderr into stdout
    )
    t = threading.Thread(target=_stream, args=(proc.stdout, prefix), daemon=True)
    t.start()
    return proc


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{_CYAN}{'─' * 54}{_RESET}")
    print(f"{_CYAN}  EchoForge V3  —  starting all services…{_RESET}")
    print(f"{_CYAN}{'─' * 54}{_RESET}\n")

    procs: list[subprocess.Popen] = []

    # Start orchestrator first — it initialises the DB
    print(f"{ORCH_PREFIX}Starting orchestrator…")
    orch = _start(ORCH_PATH, ORCH_PREFIX)
    procs.append(orch)
    time.sleep(1.5)   # small delay so the DB is ready before the bot starts

    # Start bot
    print(f"{BOT_PREFIX}Starting Telegram bot…")
    bot = _start(BOT_PATH, BOT_PREFIX)
    procs.append(bot)

    print(f"\n  Press {_RED}Ctrl+C{_RESET} to stop both services.\n")

    # ── Graceful shutdown on Ctrl+C ───────────────────────────────────────────

    def _shutdown(signum=None, frame=None) -> None:
        print(f"\n\n  Shutting down EchoForge…")
        for p in procs:
            if p.poll() is None:        # still running
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()                # force-kill if it won't stop
        print("  All services stopped. Goodbye!\n")
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Watch loop — restart a child if it dies unexpectedly ─────────────────

    while True:
        time.sleep(3)

        if orch.poll() is not None:
            print(f"\n{_RED}[ORCH] Process exited (code {orch.returncode}) — restarting…{_RESET}")
            orch = _start(ORCH_PATH, ORCH_PREFIX)
            procs[0] = orch

        if bot.poll() is not None:
            print(f"\n{_RED}[BOT ] Process exited (code {bot.returncode}) — restarting…{_RESET}")
            bot = _start(BOT_PATH, BOT_PREFIX)
            procs[1] = bot


if __name__ == "__main__":
    main()
