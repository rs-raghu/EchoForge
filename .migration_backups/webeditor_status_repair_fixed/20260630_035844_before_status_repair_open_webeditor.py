from __future__ import annotations
# ECHOFORGE_UTF8_SUBPROCESS_BOOTSTRAP
import os
os.environ.setdefault('PYTHONUTF8', '1')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
from urllib.parse import urlparse
import uuid
import subprocess
import threading
# ECHOFORGE_STAGE3_SRC_PATH_START
from pathlib import Path as _EFPath
import sys as _EFSys
_EF_ROOT_DIR=_EFPath(__file__).resolve().parents[1]
_EF_SRC_DIR=_EF_ROOT_DIR/"src"
if str(_EF_SRC_DIR) not in _EFSys.path: _EFSys.path.insert(0,str(_EF_SRC_DIR))
# ECHOFORGE_STAGE3_SRC_PATH_END


import argparse
import json
import mimetypes
import shutil
import sys
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
WEB_DIR = ROOT_DIR / "apps" / "webeditor"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from echoforge.stages.renderer.editor_project_v2 import make_v2_project, read_json, write_json, now_iso

PROJECT_DIR: Path


def safe_join(base: Path, rel: str) -> Path:
    rel = unquote(rel).replace("\\", "/").lstrip("/")
    path = (base / rel).resolve()
    base_resolved = base.resolve()
    if path != base_resolved and base_resolved not in path.parents:
        raise ValueError("Unsafe path")
    return path

# Browser media elements often cancel old Range requests while seeking.
# On Windows this appears as WinError 10053/10054 in the local dev server.
# These are normal client disconnects, not editor failures, so keep the
# terminal clean while still allowing real server exceptions to print.
def _echoforge_is_client_disconnect(exc: BaseException) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    if isinstance(exc, OSError):
        return getattr(exc, "winerror", None) in {10053, 10054, 10038} or getattr(exc, "errno", None) in {32, 104}
    return False



# ECHOFORGE_RENDER_UPLOAD_ENDPOINTS_V1
ACTIVE_RENDER_JOBS = {}


def _upload_status_path() -> Path:
    return PROJECT_DIR / "upload" / "render_upload_status.json"


def _read_render_upload_status() -> dict:
    path = _upload_status_path()
    if not path.exists():
        return {
            "ok": None,
            "running": False,
            "phase": "idle",
            "progress": 0,
            "message": "No render job has started.",
            "project_dir": str(PROJECT_DIR),
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "running": False,
            "phase": "status_read_failed",
            "progress": 0,
            "message": str(exc),
            "project_dir": str(PROJECT_DIR),
        }


def _write_render_upload_status(payload: dict) -> None:
    path = _upload_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _start_render_upload_job(payload: dict | None = None) -> dict:
    payload = payload or {}
    status = _read_render_upload_status()
    if status.get("running"):
        return {"ok": True, "already_running": True, "status": status}

    job_id = str(uuid.uuid4())
    upload = bool(payload.get("upload"))
    visibility = str(payload.get("visibility") or "private")
    schedule_time = str(payload.get("schedule_time") or payload.get("scheduleTime") or "")

    cmd = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "render_upload_project.py"),
        "--project",
        str(PROJECT_DIR),
    ]
    cmd.append("--upload" if upload else "--no-upload")
    cmd += ["--visibility", visibility]
    if schedule_time:
        cmd += ["--schedule-time", schedule_time]

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    _write_render_upload_status({
        "ok": None,
        "running": True,
        "phase": "queued",
        "progress": 1,
        "message": "Render job queued.",
        "job_id": job_id,
        "upload_enabled": upload,
        "requested_visibility": visibility,
        "schedule_time": schedule_time,
        "project_dir": str(PROJECT_DIR),
    })

    def runner() -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            ACTIVE_RENDER_JOBS[job_id] = proc
            out, err = proc.communicate()
            status_after = _read_render_upload_status()
            if proc.returncode != 0 and status_after.get("running"):
                status_after.update({
                    "ok": False,
                    "running": False,
                    "phase": "failed",
                    "progress": status_after.get("progress", 0),
                    "message": "Render/upload process failed.",
                    "stdout": (out or "")[-6000:],
                    "stderr": (err or "")[-6000:],
                })
                _write_render_upload_status(status_after)
        except Exception as exc:
            _write_render_upload_status({
                "ok": False,
                "running": False,
                "phase": "failed",
                "progress": 0,
                "message": str(exc),
                "job_id": job_id,
                "project_dir": str(PROJECT_DIR),
            })
        finally:
            ACTIVE_RENDER_JOBS.pop(job_id, None)

    threading.Thread(target=runner, daemon=True).start()
    return {"ok": True, "job_id": job_id, "started": True, "status": _read_render_upload_status()}



# ---- EchoForge status endpoint safety helpers ----
def _ef_status_file():
    return PROJECT_DIR / "upload" / "render_upload_status.json"


def _ef_default_status():
    return {
        "ok": True,
        "stage": "idle",
        "message": "Ready.",
        "running": False,
        "done": False,
        "failed": False,
        "progress": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _ef_read_status():
    try:
        p = _ef_status_file()
        if not p.exists():
            return _ef_default_status()
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        data = _ef_default_status()
        data.update({"ok": False, "stage": "status_error", "message": str(exc), "failed": True})
        return data


def _ef_write_status(data):
    p = _ef_status_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data or {})
    data.setdefault("ok", True)
    data.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data

# ---- End EchoForge status endpoint safety helpers ----

class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if exc is not None and _echoforge_is_client_disconnect(exc):
            return
        return super().handle_error(request, client_address)



# ECHOFORGE_STAGE3_RENDER_UPLOAD_SERVER_START
def _ef_read_request_json(handler):
    import json
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8")) if raw else {}
def _ef_handle_render_start(handler):
    from echoforge.stages.renderer.render_jobs import start_render_upload_job
    return handler.send_json(start_render_upload_job(PROJECT_DIR, _ef_read_request_json(handler)))
def _ef_handle_render_status(handler):
    import urllib.parse
    from echoforge.stages.renderer.render_jobs import get_job_status
    q=urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    return handler.send_json(get_job_status((q.get("job_id") or [""])[0]))
# ECHOFORGE_STAGE3_RENDER_UPLOAD_SERVER_END


class Handler(BaseHTTPRequestHandler):
    server_version = "EchoForgeWebEditorV3/1.0"

    def log_message(self, fmt: str, *args):
        return

    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_text(self, text: str, status=200, content_type="text/plain; charset=utf-8"):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_text("Not found", status=404)
            return

        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        size = path.stat().st_size
        range_header = self.headers.get("Range")

        if range_header and range_header.startswith("bytes="):
            try:
                spec = range_header.replace("bytes=", "", 1).split(",", 1)[0].strip()
                start_s, end_s = spec.split("-", 1)
                if start_s == "":
                    length = int(end_s)
                    start = max(0, size - length)
                    end = size - 1
                else:
                    start = int(start_s)
                    end = int(end_s) if end_s else size - 1
                start = max(0, min(start, size - 1))
                end = max(start, min(end, size - 1))
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with path.open("rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
            except Exception:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)


    # === EchoForge Render + Metadata + Upload API integration ===
    def _ef_read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except Exception:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _ef_root_dir(self):
        return Path(__file__).resolve().parents[1]

    def _ef_project_dir(self):
        return Path(PROJECT_DIR).resolve()

    def handle_youtube_metadata(self):
        root = self._ef_root_dir()
        project_dir = self._ef_project_dir()
        try:
            cmd = [
                sys.executable,
                str(root / "scripts" / "generate_youtube_metadata.py"),
                "--project",
                str(project_dir),
            ]
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            metadata_path = project_dir / "upload" / "youtube_metadata.json"
            data = {}
            if metadata_path.exists():
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
            elif proc.stdout.strip():
                data = json.loads(proc.stdout)
            if proc.returncode != 0:
                return self.send_json({
                    "ok": False,
                    "error": "metadata_generation_failed",
                    "stdout": proc.stdout[-4000:],
                    "stderr": proc.stderr[-4000:],
                }, status=500)
            return self.send_json({
                "ok": True,
                "metadata": data.get("metadata", data),
                "full": data,
                "path": str(metadata_path),
            })
        except Exception as exc:
            return self.send_json({"ok": False, "error": str(exc)}, status=500)

    def handle_render_upload_start(self):
        root = self._ef_root_dir()
        project_dir = self._ef_project_dir()
        upload_dir = project_dir / "upload"
        upload_dir.mkdir(parents=True, exist_ok=True)

        status_path = upload_dir / "render_upload_status.json"
        if status_path.exists():
            try:
                old_status = json.loads(status_path.read_text(encoding="utf-8"))
                if old_status.get("running"):
                    return self.send_json({
                        "ok": True,
                        "already_running": True,
                        "status": old_status,
                    })
            except Exception:
                pass

        payload = self._ef_read_json_body()
        job_id = uuid.uuid4().hex[:12]
        payload["job_id"] = job_id
        payload.setdefault("upload", True)

        request_path = upload_dir / "render_upload_request.json"
        request_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        status = {
            "ok": None,
            "running": True,
            "job_id": job_id,
            "stage": "queued",
            "project_dir": str(project_dir),
            "request_path": str(request_path),
        }
        status_path.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")

        log_path = upload_dir / "render_upload_process.log"
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        cmd = [
            sys.executable,
            str(root / "scripts" / "render_upload_project.py"),
            "--project",
            str(project_dir),
            "--request",
            str(request_path),
        ]
        subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )

        return self.send_json({
            "ok": True,
            "job_id": job_id,
            "status": status,
            "log_path": str(log_path),
        })

    def handle_render_upload_status(self):
        project_dir = self._ef_project_dir()
        status_path = project_dir / "upload" / "render_upload_status.json"
        if status_path.exists():
            try:
                return self.send_json(json.loads(status_path.read_text(encoding="utf-8")))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=500)
        return self.send_json({"ok": True, "running": False, "stage": "idle"})
    # === End EchoForge Render + Metadata + Upload API integration ===

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/api/render-upload-status", "/media/upload/render_upload_status.json"):
            return self.send_json(_ef_read_status())



        # ECHOFORGE_DO_GET_PATH_INIT

        parsed = urlparse(getattr(self, 'path', '/') or '/')

        path = parsed.path or '/'

        if path == "/api/render-upload-status":
            return self.send_json(_read_render_upload_status())
        _ef_api_path = urlparse(self.path).path
        if _ef_api_path == "/api/youtube-metadata":
            return self.handle_youtube_metadata()
        if _ef_api_path == "/api/render-upload/status":
            return self.handle_render_upload_status()

        # ECHOFORGE_STAGE3_RENDER_UPLOAD_GET

        if self.path.startswith('/api/render/status'):

            return _ef_handle_render_status(self)
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            return self.send_file(WEB_DIR / "index.html")
        if path == "/api/project":
            result = make_v2_project(PROJECT_DIR, force=False)
            data = read_json(PROJECT_DIR / "editor" / "editor_project.json", {})
            data["_server"] = {"prepare_result": result, "project_dir": str(PROJECT_DIR)}
            return self.send_json(data)
        if path.startswith("/media/"):
            try:
                return self.send_file(safe_join(PROJECT_DIR, path[len("/media/") :]))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=400)
        if path.startswith("/root/"):
            try:
                return self.send_file(safe_join(ROOT_DIR, path[len("/root/") :]))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=400)
        try:
            rel = path.lstrip("/") or "index.html"
            return self.send_file(safe_join(WEB_DIR, rel))
        except Exception as exc:
            return self.send_json({"ok": False, "error": str(exc)}, status=400)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/api/render-upload-status",):
            return self.send_json(_ef_read_status())


        path = urlparse(self.path).path
        if path == "/api/render-upload-start":
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
                payload = json.loads(raw or "{}")
            except Exception:
                payload = {}
            return self.send_json(_start_render_upload_job(payload))
        _ef_api_path = urlparse(self.path).path
        if _ef_api_path == "/api/youtube-metadata":
            return self.handle_youtube_metadata()
        if _ef_api_path == "/api/render-upload/start":
            return self.handle_render_upload_start()

        # ECHOFORGE_STAGE3_RENDER_UPLOAD_POST

        if self.path == '/api/render/start':

            return _ef_handle_render_start(self)
        parsed = urlparse(self.path)
        if parsed.path != "/api/project":
            return self.send_json({"ok": False, "error": "Unknown endpoint"}, status=404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            if data.get("schema") != "echoforge.webeditor.v2":
                return self.send_json({"ok": False, "error": "Invalid editor schema"}, status=400)
            editor_path = PROJECT_DIR / "editor" / "editor_project.json"
            backup_dir = PROJECT_DIR / "editor" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            if editor_path.exists():
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(editor_path, backup_dir / f"{stamp}_editor_project.json")
            data["updated_at"] = now_iso()
            write_json(editor_path, data)
            return self.send_json({"ok": True, "saved": str(editor_path)})
        except Exception as exc:
            return self.send_json({"ok": False, "error": str(exc)}, status=500)


def main():
    global PROJECT_DIR
    parser = argparse.ArgumentParser(description="Open EchoForge WebEditor V3.")
    parser.add_argument("--project", required=True, help="Project directory.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--force-v2", action="store_true", help="Rebuild editor_project.json before opening.")
    args = parser.parse_args()

    PROJECT_DIR = Path(args.project).resolve()
    if not PROJECT_DIR.exists():
        raise SystemExit(f"Project not found: {PROJECT_DIR}")

    prep = make_v2_project(PROJECT_DIR, force=args.force_v2)
    print(json.dumps(prep, indent=2, ensure_ascii=False))

    url = f"http://{args.host}:{args.port}/"
    server = QuietThreadingHTTPServer((args.host, args.port), Handler)
    print(f"\nEchoForge WebEditor V3 running at {url}")
    print("Keep this terminal open. Press Ctrl+C to stop.\n")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server
    try:
        _ef_write_status(_ef_read_status())
    except Exception:
        pass
    server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping WebEditor...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
