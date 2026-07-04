from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBEDITOR = ROOT / "apps" / "webeditor_legacy"


def main() -> int:
    if not WEBEDITOR.exists():
        print("Legacy WebEditor not found. Run apply_webeditor_legacy_ui_revival.py first.")
        return 1
    run_bat = WEBEDITOR / "run.bat"
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "EchoForge Legacy WebEditor", str(run_bat)], cwd=str(WEBEDITOR))
        return 0
    print("On non-Windows, run these manually:")
    print(f"cd {WEBEDITOR / 'backend'} && python main.py")
    print(f"cd {WEBEDITOR / 'frontend'} && npm install && npm run dev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
