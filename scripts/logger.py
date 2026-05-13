"""
logger.py

Central logging configuration for the EchoForge pipeline.

Sets up the root logger exactly once on first import:
  • RotatingFileHandler  → Logs/echoforge.log  (5 MB per file, 5 backups)
  • StreamHandler        → stdout  (console output unchanged for live monitoring)

Every other module gets its own named logger via get_logger(__name__), which
inherits both handlers automatically from the root logger.

Usage in any module:
    from logger import get_logger
    log = get_logger(__name__)

    log.info("✅ Something succeeded")
    log.warning("⚠️  Something looks off")
    log.error("❌ Something failed: %s", exc)
    log.debug("   detail only needed when debugging")

Log levels used across the pipeline:
    DEBUG    — very verbose: segment previews, upload %, separator banners
    INFO     — normal pipeline flow: phase markers, file paths, success lines
    WARNING  — recoverable issues: retries, missing optional files, skipped steps
    ERROR    — failures that halt or skip a phase

The LOG_LEVEL env variable controls the minimum level written to the file
(default: DEBUG so nothing is silently dropped).  The console handler always
uses INFO so routine runs stay readable.

ROTATING FILE DETAILS
─────────────────────
Max 5 MB per file, 5 backup files kept → at most ~30 MB of log history.
Files are named:
    echoforge.log          ← current
    echoforge.log.1        ← most recent rollover
    echoforge.log.2 … .5  ← older
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from config import LOGS_DIR

# ─── Constants ────────────────────────────────────────────────────────────────

LOG_FILE       = os.path.join(LOGS_DIR, "echoforge.log")
LOG_MAX_BYTES  = 5 * 1024 * 1024   # 5 MB per file
LOG_BACKUP_CNT = 5                  # keep 5 rotated files

# Read desired file-level verbosity from the environment; default to DEBUG so
# every message is persisted.  Console always uses INFO.
_raw_level    = os.getenv("LOG_LEVEL", "DEBUG").upper()
LOG_LEVEL     = getattr(logging, _raw_level, logging.DEBUG)

# Log record format — tab-separated columns make grep and awk easy.
_FMT   = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


# ─── Setup (runs once on first import) ────────────────────────────────────────

def _setup_root_logger() -> None:
    """Configure the root logger with file + stream handlers."""
    root = logging.getLogger()

    # Guard: don't add duplicate handlers if this module is accidentally
    # imported more than once (e.g. via importlib reload in tests).
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)   # let handlers filter individually

    os.makedirs(LOGS_DIR, exist_ok=True)

    # ── Rotating file handler (DEBUG+) ─────────────────────────────────────
    try:
        fh = RotatingFileHandler(
            LOG_FILE,
            maxBytes    = LOG_MAX_BYTES,
            backupCount = LOG_BACKUP_CNT,
            encoding    = "utf-8",
        )
        fh.setLevel(LOG_LEVEL)
        fh.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
        root.addHandler(fh)
    except Exception as e:
        # Log dir might not be writable in some environments — warn but don't crash.
        print(f"⚠️  logger.py: could not create log file at {LOG_FILE}: {e}", file=sys.stderr)

    # ── Stream handler (INFO+ → stdout) ────────────────────────────────────
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    root.addHandler(sh)


_setup_root_logger()


# ─── Public API ───────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger that inherits both handlers from the root logger.

    Call once at module level:
        log = get_logger(__name__)
    """
    return logging.getLogger(name)