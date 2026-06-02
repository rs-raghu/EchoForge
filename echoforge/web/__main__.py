"""Command-line launcher for EchoForge Web Studio."""

from __future__ import annotations

import argparse
import os
import sys


def _configure_stdio() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Run EchoForge Web Studio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--fastapi",
        action="store_true",
        help="Use FastAPI/uvicorn when those packages are installed.",
    )
    args = parser.parse_args()

    if args.fastapi:
        try:
            import uvicorn

            uvicorn.run("echoforge.web.api:app", host=args.host, port=args.port, reload=False)
            return
        except ImportError:
            print("FastAPI server dependencies are not installed; using the built-in local server.")

    from .dev_server import run

    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
