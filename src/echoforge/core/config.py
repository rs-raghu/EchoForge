import os
from dataclasses import dataclass
from pathlib import Path

from echoforge.core.paths import ROOT_DIR


@dataclass(frozen=True)
class Settings:
    app_name: str = "EchoForge"
    environment: str = os.getenv("ECHOFORGE_ENV", "dev")

    youtube_charts_url: str = os.getenv(
        "YOUTUBE_CHARTS_URL",
        "https://charts.youtube.com/charts/TopSongs/global/weekly",
    )

    max_songs: int = int(os.getenv("MAX_SONGS", "100"))

    genius_access_token: str | None = os.getenv("GENIUS_ACCESS_TOKEN") or None

    webeditor_backend_host: str = os.getenv("WEBEDITOR_BACKEND_HOST", "127.0.0.1")
    webeditor_backend_port: int = int(os.getenv("WEBEDITOR_BACKEND_PORT", "8765"))
    webeditor_frontend_port: int = int(os.getenv("WEBEDITOR_FRONTEND_PORT", "5173"))

    youtube_client_secret_path: Path | None = (
        Path(os.getenv("YOUTUBE_CLIENT_SECRET_PATH"))
        if os.getenv("YOUTUBE_CLIENT_SECRET_PATH")
        else None
    )

    youtube_token_path: Path | None = (
        Path(os.getenv("YOUTUBE_TOKEN_PATH"))
        if os.getenv("YOUTUBE_TOKEN_PATH")
        else None
    )


settings = Settings()


def print_settings() -> None:
    print(f"App: {settings.app_name}")
    print(f"Environment: {settings.environment}")
    print(f"Root: {ROOT_DIR}")
    print(f"YouTube chart URL: {settings.youtube_charts_url}")
    print(f"Max songs: {settings.max_songs}")
    print(f"WebEditor backend: {settings.webeditor_backend_host}:{settings.webeditor_backend_port}")
    print(f"WebEditor frontend port: {settings.webeditor_frontend_port}")