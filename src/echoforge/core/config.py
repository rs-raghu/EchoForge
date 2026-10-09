import os
from dataclasses import dataclass, field
from pathlib import Path

from echoforge.core.paths import ROOT_DIR


def integer_setting(name, default, minimum=1, maximum=65535):
    try: result=int(os.getenv(name,str(default)))
    except ValueError: raise ValueError(f'{name} must be an integer') from None
    if not minimum <= result <= maximum: raise ValueError(f'{name} is outside its supported range')
    return result


def credential_path(name, alias):
    raw=os.getenv(name) or os.getenv(alias)
    if not raw: return None
    value=Path(raw).expanduser()
    return value.resolve() if value.is_absolute() else (ROOT_DIR/value).resolve()


@dataclass(frozen=True)
class Settings:
    app_name: str='EchoForge'
    environment: str=field(default_factory=lambda:os.getenv('ECHOFORGE_ENV','dev'))
    youtube_charts_url: str=field(default_factory=lambda:os.getenv('YOUTUBE_CHARTS_URL','https://charts.youtube.com/charts/TopSongs/global/weekly'))
    max_songs: int=field(default_factory=lambda:integer_setting('MAX_SONGS',100,1,500))
    genius_access_token: str | None=field(default_factory=lambda:os.getenv('GENIUS_ACCESS_TOKEN') or None, repr=False)
    webeditor_backend_host: str=field(default_factory=lambda:os.getenv('WEBEDITOR_BACKEND_HOST','127.0.0.1'))
    webeditor_backend_port: int=field(default_factory=lambda:integer_setting('WEBEDITOR_BACKEND_PORT',8765))
    webeditor_frontend_port: int=field(default_factory=lambda:integer_setting('WEBEDITOR_FRONTEND_PORT',5173))
    youtube_client_secret_path: Path | None=field(default_factory=lambda:credential_path('YOUTUBE_CLIENT_SECRET_PATH','YOUTUBE_CLIENT_SECRET_FILE'))
    youtube_token_path: Path | None=field(default_factory=lambda:credential_path('YOUTUBE_TOKEN_PATH','YOUTUBE_TOKEN_FILE'))


settings = Settings()


def print_settings() -> None:
    print(f"App: {settings.app_name}")
    print(f"Environment: {settings.environment}")
    print(f"Root: {ROOT_DIR}")
    print(f"YouTube chart URL: {settings.youtube_charts_url}")
    print(f"Max songs: {settings.max_songs}")
    print(f"WebEditor backend: {settings.webeditor_backend_host}:{settings.webeditor_backend_port}")
    print(f"WebEditor frontend port: {settings.webeditor_frontend_port}")