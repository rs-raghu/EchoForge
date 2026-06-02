"""Small local HTTP server for the Web Studio shell.

This lets the app run before FastAPI and uvicorn are installed. The API shape
matches echoforge.web.api so the frontend does not care which server is active.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import service

ROOT_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT_DIR / "apps" / "web-studio" / "frontend" / "dist"


def _configure_stdio() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class StudioRequestHandler(BaseHTTPRequestHandler):
    server_version = "EchoForgeWebStudio/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                self._json(service.health())
            elif path == "/api/dashboard":
                self._json(service.dashboard())
            elif path == "/api/projects":
                limit = int(query.get("limit", ["100"])[0])
                state = query.get("state", [None])[0]
                self._json(service.list_projects(limit=limit, state=state))
            elif path == "/api/templates":
                self._json(service.list_templates())
            elif path == "/api/settings":
                self._json(service.get_app_settings())
            elif path == "/api/jobs":
                project_id = query.get("project_id", [None])[0]
                limit = int(query.get("limit", ["80"])[0])
                self._json(service.list_jobs(project_id=project_id, limit=limit))
            elif path.startswith("/api/jobs/"):
                job_id = int(path.split("/")[3])
                self._json(service.get_job(job_id))
            elif path.startswith("/api/projects/") and "/media/" in path:
                parts = path.split("/")
                project_id = unquote(parts[3])
                kind = unquote(parts[5])
                self._file(service.project_media_path(project_id, kind))
            elif path.startswith("/api/projects/") and path.endswith("/files"):
                project_id = unquote(path.split("/")[3])
                self._json(service.list_project_files(project_id))
            elif path.startswith("/api/projects/") and path.endswith("/lyrics/versions"):
                project_id = unquote(path.split("/")[3])
                self._json(service.list_lyrics_versions(project_id))
            elif path.startswith("/api/projects/") and path.endswith("/lyrics"):
                project_id = unquote(path.split("/")[3])
                self._json(service.get_lyrics(project_id))
            elif path.startswith("/api/projects/") and path.endswith("/timestamps/versions"):
                project_id = unquote(path.split("/")[3])
                self._json(service.list_timestamp_versions(project_id))
            elif path.startswith("/api/projects/") and path.endswith("/timestamps"):
                project_id = unquote(path.split("/")[3])
                self._json(service.get_timestamps(project_id))
            elif path.startswith("/api/projects/") and path.endswith("/design"):
                project_id = unquote(path.split("/")[3])
                self._json(service.get_project_design(project_id))
            elif path.startswith("/api/projects/") and path.endswith("/render-readiness"):
                project_id = unquote(path.split("/")[3])
                self._json(service.render_readiness(project_id))
            elif path.startswith("/api/projects/") and path.endswith("/upload/metadata"):
                project_id = unquote(path.split("/")[3])
                self._json(service.get_upload_metadata(project_id))
            elif path.startswith("/api/projects/"):
                project_id = unquote(path.split("/")[3])
                self._json(service.get_project(project_id))
            elif path == "/api/logs":
                project_id = query.get("project_id", [None])[0]
                limit = int(query.get("limit", ["80"])[0])
                self._json(service.read_logs(project_id=project_id, limit=limit))
            else:
                self._static(path)
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "Project not found")
        except (FileNotFoundError, ValueError):
            self._error(HTTPStatus.NOT_FOUND, "Media file not found")
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        payload = self._read_json()

        try:
            if path == "/api/projects":
                self._json(service.create_project(payload), status=HTTPStatus.CREATED)
            elif path == "/api/discovery/youtube-charts":
                self._json(
                    service.run_discovery(
                        limit=int(payload.get("limit", 20)),
                        country=str(payload.get("country", "US")),
                        force=bool(payload.get("force", False)),
                    )
                )
            elif path == "/api/queue/stage-next":
                project = service.stage_next_project()
                if not project:
                    self._error(HTTPStatus.NOT_FOUND, "Queue is empty")
                else:
                    self._json(project)
            elif path.startswith("/api/projects/") and path.endswith("/actions"):
                project_id = unquote(path.split("/")[3])
                action = str(payload.get("action") or "")
                self._json(service.run_project_action(project_id, action, payload))
            elif path.startswith("/api/projects/") and path.endswith("/lyrics/approve"):
                project_id = unquote(path.split("/")[3])
                self._json(service.approve_lyrics(project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/timestamps/validate"):
                project_id = unquote(path.split("/")[3])
                self._json(service.validate_timestamps(project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/timestamps/shift"):
                project_id = unquote(path.split("/")[3])
                self._json(service.shift_timestamps(project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/timestamps/approve"):
                project_id = unquote(path.split("/")[3])
                self._json(service.approve_timestamps(project_id, payload))
            elif path.startswith("/api/projects/") and "/jobs/" in path:
                parts = path.split("/")
                project_id = unquote(parts[3])
                job_type = unquote(parts[5])
                self._json(service.start_project_job(project_id, job_type, payload))
            elif path.startswith("/api/projects/") and path.endswith("/upload/metadata/generate"):
                project_id = unquote(path.split("/")[3])
                self._json(service.generate_upload_metadata(project_id))
            elif path.startswith("/api/projects/") and path.endswith("/upload/approve"):
                project_id = unquote(path.split("/")[3])
                self._json(service.approve_upload(project_id, payload))
            elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = int(path.split("/")[3])
                self._json(service.cancel_job(job_id))
            else:
                self._error(HTTPStatus.NOT_FOUND, "Route not found")
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "Project not found")
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        payload = self._read_json()

        try:
            if path.startswith("/api/projects/") and path.endswith("/lyrics"):
                project_id = unquote(path.split("/")[3])
                draft = query.get("draft", ["false"])[0].lower() in {"1", "true", "yes"}
                self._json(service.save_lyrics(project_id, payload, draft=draft))
            elif path.startswith("/api/projects/") and path.endswith("/timestamps"):
                project_id = unquote(path.split("/")[3])
                draft = query.get("draft", ["false"])[0].lower() in {"1", "true", "yes"}
                self._json(service.save_timestamps(project_id, payload, draft=draft))
            elif path.startswith("/api/projects/") and path.endswith("/design"):
                project_id = unquote(path.split("/")[3])
                self._json(service.save_project_design(project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/upload/metadata"):
                project_id = unquote(path.split("/")[3])
                self._json(service.save_upload_metadata(project_id, payload))
            elif path == "/api/settings":
                self._json(service.save_app_settings(payload))
            else:
                self._error(HTTPStatus.NOT_FOUND, "Route not found")
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "Project not found")
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status=status)

    def _file(self, path: Path) -> None:
        content = path.read_bytes()
        mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK.value)
        self.send_header("content-type", mime_type)
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            request_path = "/index.html"
        candidate = (STATIC_DIR / request_path.lstrip("/")).resolve()
        static_root = STATIC_DIR.resolve()
        if not str(candidate).startswith(str(static_root)) or not candidate.exists() or not candidate.is_file():
            candidate = STATIC_DIR / "index.html"

        if not candidate.exists():
            self._error(
                HTTPStatus.NOT_FOUND,
                "Frontend is not built yet. Run the web-studio frontend build first.",
            )
            return

        content = candidate.read_bytes()
        mime_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK.value)
        self.send_header("content-type", mime_type)
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    service.init_web_studio()
    server = ThreadingHTTPServer((host, port), StudioRequestHandler)
    print(f"EchoForge Web Studio running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Run the EchoForge Web Studio local server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
