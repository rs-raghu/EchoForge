import os

from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(ROOT_DIR, ".env")

load_dotenv(dotenv_path=ENV_PATH)

DATABASE_PATH = os.path.join(ROOT_DIR, "database", "echoforge.db")
WORKSPACES_DIR = os.path.join(ROOT_DIR, "workspaces")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
REMOTION_DIR = os.path.join(ROOT_DIR, "renderer", "remotion")

os.makedirs(WORKSPACES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)


def validate_config():
    """Validate local Web Studio runtime paths."""
    os.makedirs(WORKSPACES_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    return True
