from __future__ import annotations

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


class Handler(BaseHTTPRequestHandler):
    server_version = "EchoForgeWebEditorV2/1.0"

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
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            return self.send_file(WEB_DIR / "index.html")

        if path == "/api/project":
            result = make_v2_project(PROJECT_DIR, force=False)
            data = read_json(PROJECT_DIR / "editor" / "editor_project.json", {})
            data["_server"] = {
                "prepare_result": result,
                "project_dir": str(PROJECT_DIR),
            }
            return self.send_json(data)

        if path.startswith("/media/"):
            try:
                rel = path[len("/media/") :]
                return self.send_file(safe_join(PROJECT_DIR, rel))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=400)

        if path.startswith("/root/"):
            try:
                rel = path[len("/root/") :]
                return self.send_file(safe_join(ROOT_DIR, rel))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=400)

        try:
            rel = path.lstrip("/") or "index.html"
            return self.send_file(safe_join(WEB_DIR, rel))
        except Exception as exc:
            return self.send_json({"ok": False, "error": str(exc)}, status=400)

    def do_POST(self):
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

    parser = argparse.ArgumentParser(description="Open EchoForge Clipchamp-style WebEditor V2.")
    parser.add_argument("--project", required=True, help="Project directory.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--force-v2", action="store_true", help="Rebuild editor_project.json as V2 before opening.")
    args = parser.parse_args()

    PROJECT_DIR = Path(args.project).resolve()
    if not PROJECT_DIR.exists():
        raise SystemExit(f"Project not found: {PROJECT_DIR}")

    prep = make_v2_project(PROJECT_DIR, force=args.force_v2)
    print(json.dumps(prep, indent=2, ensure_ascii=False))

    url = f"http://{args.host}:{args.port}/"
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"\nEchoForge WebEditor V2 running at {url}")
    print("Keep this terminal open. Press Ctrl+C to stop.\n")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping WebEditor...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
