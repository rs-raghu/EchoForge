import os
from dotenv import load_dotenv

# Find the absolute root directory of the project
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT_DIR, '.env')

# Safely load the .env file
load_dotenv(dotenv_path=ENV_PATH)

# --- Secret Keys ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# --- Core Paths ---
DATABASE_PATH = os.path.join(ROOT_DIR, "database", "echoforge.db")
WORKSPACES_DIR = os.path.join(ROOT_DIR, "workspaces")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
REMOTION_DIR = os.path.join(ROOT_DIR, "remotion")

# --- Ensure Required Directories Exist ---
os.makedirs(WORKSPACES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def validate_config():
    """
    Validates that all critical environment variables are present.
    Call this on startup to prevent the app from crashing later.
    """
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "❌ TELEGRAM_BOT_TOKEN is missing! "
            "Please add it to your .env file in the project root."
        )
    return True