from __future__ import annotations
# ECHOFORGE_UTF8_SUBPROCESS_BOOTSTRAP
import os
os.environ.setdefault('PYTHONUTF8', '1')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# ECHOFORGE_SAFE_JSON_STDOUT_FOR_WINDOWS
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from echoforge.stages.tubeharbor.metadata_generator import main

if __name__ == "__main__":
    raise SystemExit(main())
