"""Load the repository environment before modules evaluate their settings."""
from dotenv import load_dotenv
from echoforge.core.paths import ROOT_DIR

load_dotenv(ROOT_DIR / ".env", override=False)
