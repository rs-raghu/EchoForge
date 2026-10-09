from __future__ import annotations
import argparse
import json
import mimetypes
import shutil
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from echoforge.core.paths import ROOT_DIR
from echoforge.core.security import asset_path, validate_editor
from echoforge.core.storage import atomic_json, read_json, file_lock
from echoforge.stages.renderer.editor_project_v2 import make_v2_project, now_iso
from echoforge.stages.renderer.render_jobs import start_render_upload_job, get_job_status, project_job_status

WEB_DIR = ROOT_DIR / "apps/webeditor"
PROJECT_DIR: Path
MAX_BODY = 8 * 1024 * 1024


def safe_join(base, relative):
    path = (base / unquote(relative)).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError("Unsafe path")
    return path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def trusted_request(self, write=False):
        # Reject DNS rebinding and browser requests originating from other sites.
        host = urlparse("http://" + self.headers.get("Host", "")).hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise PermissionError("Local host required")
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host"):
            raise PermissionError("Same-origin request required")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PermissionError("Cross-site request denied")
        if write and self.headers.get_content_type() != "application/json":
            raise PermissionError("JSON requests required")

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("Invalid request size")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def send_file(self, path):
        if not path.is_file():
            return self.send_json({"ok":False, "error":"File not found"}, 404)
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            try:
                unit, bounds = range_header.split("=", 1)
                left, right = bounds.split("-", 1)
                if unit != "bytes" or "," in bounds:
                    raise ValueError()
                if left:
                    start = int(left); end = min(int(right), size - 1) if right else size - 1
                else:
                    start = max(0, size - int(right))
                if start < 0 or start >= size or end < start:
                    raise ValueError()
                status = 206
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = stream.read(min(512 * 1024, remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining -= len(chunk)

    def metadata(self):
        path = PROJECT_DIR / "upload/youtube_metadata.json"
        data = read_json(path, {})
        if not data:
            from echoforge.stages.tubeharbor.metadata_generator import generate_youtube_metadata
            data = generate_youtube_metadata(PROJECT_DIR, use_gemini=False)
        return {"ok":True, "metadata":data.get("metadata", data), "full":data}

    def do_GET(self):
        try:
            self.trusted_request()
            parsed = urlparse(self.path); path = parsed.path
            if path == "/api/project":
                result = make_v2_project(PROJECT_DIR, force=False)
                if not result.get("ok"): return self.send_json(result, 409)
                return self.send_json(read_json(PROJECT_DIR / "editor/editor_project.json"))
            if path == "/api/youtube-metadata": return self.send_json(self.metadata())
            if path == "/api/render/status":
                return self.send_json(get_job_status(parse_qs(parsed.query).get("job_id", [""])[0]))
            if path in {"/api/render-upload/status", "/api/render-upload-status"}:
                return self.send_json(project_job_status(PROJECT_DIR))
            if path.startswith("/root/"):
                raw = unquote(path[6:])
                if not raw.startswith("assets/"): raise PermissionError("Only shared assets are public")
                return self.send_file(asset_path(PROJECT_DIR, raw, ROOT_DIR))
            if path.startswith("/media/"):
                return self.send_file(asset_path(PROJECT_DIR, path[7:], ROOT_DIR))
            if path in {"/", "/index.html", "/app.js", "/style.css"}:
                return self.send_file(safe_join(WEB_DIR, path.lstrip("/") or "index.html"))
            return self.send_json({"ok":False, "error":"Not found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except PermissionError as exc:
            self.send_json({"ok":False, "error":str(exc)}, 403)
        except (ValueError, OSError) as exc:
            self.send_json({"ok":False, "error":str(exc)}, 400)
        except Exception as exc:
            self.send_json({"ok":False, "error":str(exc)}, 500)

    def do_POST(self):
        try:
            self.trusted_request(write=True)
            payload = self.body(); path = urlparse(self.path).path
            if path == "/api/project":
                if payload.get("schema") != "echoforge.webeditor.v2":
                    raise ValueError("Invalid editor schema")
                validate_editor(payload, PROJECT_DIR)
                editor = PROJECT_DIR / "editor/editor_project.json"
                with file_lock(editor.with_suffix(".lock")):
                    current = read_json(editor, {})
                    if current.get("revision", 0) != payload.get("revision", 0):
                        return self.send_json({"ok":False, "error":"Project changed in another editor; reload before saving"}, 409)
                    if editor.exists():
                        backup = editor.parent / "backups" / f"{uuid.uuid4().hex}_editor_project.json"
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(editor, backup)
                    payload.update(updated_at=now_iso(), revision=current.get("revision", 0) + 1)
                    payload.pop("_server", None)
                    atomic_json(editor, payload)
                return self.send_json({"ok":True, "revision":payload["revision"]})
            if path == "/api/youtube-metadata": return self.send_json(self.metadata())
            if path in {"/api/render/start", "/api/render-upload/start", "/api/render-upload-start"}:
                return self.send_json(start_render_upload_job(PROJECT_DIR, payload))
            return self.send_json({"ok":False, "error":"Not found"}, 404)
        except PermissionError as exc:
            self.send_json({"ok":False, "error":str(exc)}, 403)
        except (ValueError, TypeError) as exc:
            self.send_json({"ok":False, "error":str(exc)}, 400)
        except Exception as exc:
            self.send_json({"ok":False, "error":str(exc)}, 500)


def main():
    global PROJECT_DIR
    parser = argparse.ArgumentParser(description="Open EchoForge WebEditor")
    parser.add_argument("--project", required=True)
    parser.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--force-v2", action="store_true")
    args = parser.parse_args()
    PROJECT_DIR = Path(args.project).resolve()
    if not PROJECT_DIR.is_dir(): raise SystemExit("Project not found")
    result = make_v2_project(PROJECT_DIR, force=args.force_v2)
    if not result.get("ok"): raise SystemExit(result.get("reason", "Project preparation failed"))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{server.server_port}/"
    print(f"WebEditor: {url}", flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
