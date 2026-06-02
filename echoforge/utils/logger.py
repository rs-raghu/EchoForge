"""
utils/logger.py

Centralised logging configuration for EchoForge V3.

Every module calls get_logger(__name__) once at the top level and uses the
returned logger. Two handlers are attached:

  Console  → INFO+   (clean output, only important messages)
  File     → DEBUG+  (full trace, every detail, written to logs/echoforge.log)

The file does NOT propagate to the root logger, preventing double-printing.

USAGE:
    from echoforge.utils.logger import get_logger
    log = get_logger(__name__)
    log.info("Pipeline started")
    log.debug("Detailed timing: %.3f s", elapsed)
    log.warning("Retrying…")
    log.error("❌ Worker failed: %s", exc)
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Resolve paths relative to the project root (two levels up from this file)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "echoforge.log")

# Rotating file: 5 MB per file, keep 5 backups → max ~25 MB of log history
_MAX_BYTES   = 5 * 1024 * 1024
_BACKUP_CNT  = 5

_FMT     = "%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Ensure the logs directory exists before the first handler tries to open the file
os.makedirs(LOGS_DIR, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger with console (INFO) and rotating file (DEBUG) handlers.
    Safe to call multiple times with the same name — handlers are added only once.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger   # already configured

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)

    # ── Console handler (INFO+) ────────────────────────────────────────────────
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # ── Rotating file handler (DEBUG+) ─────────────────────────────────────────
    try:
        fh = RotatingFileHandler(
            LOG_FILE,
            maxBytes    = _MAX_BYTES,
            backupCount = _BACKUP_CNT,
            encoding    = "utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as exc:
        print(f"⚠️  Could not open log file {LOG_FILE}: {exc}", file=sys.stderr)

    logger.propagate = False
    return logger


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log = get_logger("test")
    log.debug("DEBUG   — file only")
    log.info ("INFO    — console + file")
    log.warning("WARNING — console + file")
    log.error  ("ERROR   — console + file")
    print(f"\nLog file: {LOG_FILE}")
