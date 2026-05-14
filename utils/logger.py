import logging
import os
import sys

# Find the root directory of the project (two levels up from this file)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Create a central logs folder if it doesn't exist
LOGS_DIR = os.path.join(ROOT_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# Master log file
LOG_FILE = os.path.join(LOGS_DIR, 'echoforge.log')

def get_logger(name: str) -> logging.Logger:
    """
    Creates and configures a standardized logger for the EchoForge system.
    Outputs INFO to the console and DEBUG to a central echoforge.log file.
    """
    logger = logging.getLogger(name)
    
    # Prevent adding multiple duplicate handlers if the logger is called multiple times
    if not logger.handlers:
        # Catch all levels; we will filter them in the handlers
        logger.setLevel(logging.DEBUG) 

        # Create a standardized, highly readable log format
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 1. Console Handler (Only show INFO, WARNING, ERROR, CRITICAL to keep terminal clean)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # 2. File Handler (Log EVERYTHING, including deep DEBUG traces, to the file)
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Prevent log messages from propagating up to the root logger (prevents double-printing)
        logger.propagate = False

    return logger

# --- Independent Testing ---
if __name__ == "__main__":
    log = get_logger("TestLogger")
    log.info("This is an info message (shows in terminal and file).")
    log.debug("This is a debug message (shows ONLY in the file).")
    log.warning("This is a warning!")
    log.error("This is an error!")
    print(f"Check the log file at: {LOG_FILE}")