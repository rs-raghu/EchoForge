import logging
import sys
from echoforge.core.paths import ROOT_DIR

_logger_initialized = False

def setup_logging():
    global _logger_initialized
    if _logger_initialized:
        return
    
    log_dir = ROOT_DIR / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "echoforge.log"
    
    # Configure root logger
    logger = logging.getLogger("echoforge")
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # File handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    _logger_initialized = True

def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)