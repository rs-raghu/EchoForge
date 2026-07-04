from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run_python_script(script_name: str, args: list[str]) -> int:
    script = SCRIPTS / script_name
    if not script.exists():
        print(f"Missing script: scripts\\{script_name}")
        return 2
    return subprocess.call([sys.executable, str(script), *args], cwd=str(ROOT))


def run_echoforge(args: list[str]) -> int:
    return subprocess.call([sys.executable, "-m", "echoforge", *args], cwd=str(ROOT))


def first_existing_script(names: list[str]) -> str | None:
    for name in names:
        if (SCRIPTS / name).exists():
            return name
    return None


def print_help() -> int:
    print("""
EchoForge clean runner

Base commands:
  run.bat init
  run.bat status
  run.bat doctor
  run.bat workflow
  run.bat all
  run.bat songscout ...
  run.bat project ...
  run.bat musevault ...
  run.bat verselock ...

Renderer/WebEditor/TubeHarbor commands:
  run.bat renderer prepare --project "projects\\0001_song_artist" --force
  run.bat renderer render  --project "projects\\0001_song_artist"
  run.bat webeditor open   --project "projects\\0001_song_artist"
  run.bat tubeharbor metadata --project "projects\\0001_song_artist"

Optional upload commands, if the matching upload script exists:
  run.bat tubeharbor upload --project "projects\\0001_song_artist"
  run.bat tubeharbor render-upload --project "projects\\0001_song_artist"

Examples:
  run.bat renderer prepare --project "projects\\0001_dai-dai_shakira-and-burna-boy" --force
  run.bat webeditor open --project "projects\\0001_dai-dai_shakira-and-burna-boy"
  run.bat renderer render --project "projects\\0001_dai-dai_shakira-and-burna-boy"
  run.bat tubeharbor metadata --project "projects\\0001_dai-dai_shakira-and-burna-boy"
""".strip())
    return 0


def renderer(args: list[str]) -> int:
    if not args or args[0] in {"-h", "--help", "help"}:
        print("""
Renderer commands:
  run.bat renderer prepare --project <project> [--force]
  run.bat renderer render  --project <project>
""".strip())
        return 0

    action, rest = args[0], args[1:]
    if action == "prepare":
        return run_python_script("prepare_editor_project.py", rest)
    if action == "render":
        return run_python_script("render_project.py", rest)

    print(f"Unknown renderer command: {action}")
    return 2


def webeditor(args: list[str]) -> int:
    if not args or args[0] in {"-h", "--help", "help"}:
        print("""
WebEditor commands:
  run.bat webeditor open --project <project>
""".strip())
        return 0

    action, rest = args[0], args[1:]
    if action == "open":
        return run_python_script("open_webeditor.py", rest)

    print(f"Unknown webeditor command: {action}")
    return 2


def tubeharbor(args: list[str]) -> int:
    if not args or args[0] in {"-h", "--help", "help"}:
        print("""
TubeHarbor commands:
  run.bat tubeharbor metadata --project <project> [--use-gemini|--no-gemini]
  run.bat tubeharbor upload --project <project>
  run.bat tubeharbor render-upload --project <project>
""".strip())
        return 0

    action, rest = args[0], args[1:]
    if action == "metadata":
        return run_python_script("generate_youtube_metadata.py", rest)

    if action == "upload":
        script = first_existing_script([
            "upload_to_youtube.py",
            "youtube_upload.py",
            "tubeharbor_upload.py",
            "upload_project.py",
        ])
        if not script:
            print("No TubeHarbor upload script found yet. Expected one of:")
            print("  scripts\\upload_to_youtube.py")
            print("  scripts\\youtube_upload.py")
            print("  scripts\\tubeharbor_upload.py")
            print("  scripts\\upload_project.py")
            return 2
        return run_python_script(script, rest)

    if action in {"render-upload", "render_upload", "render-and-upload"}:
        script = first_existing_script([
            "render_and_upload_project.py",
            "render_upload_project.py",
            "stage3_render_upload.py",
            "tubeharbor_render_upload.py",
        ])
        if not script:
            print("No render+upload script found yet. The WebEditor Render button may use the server job endpoint instead.")
            print("Expected one of:")
            print("  scripts\\render_and_upload_project.py")
            print("  scripts\\render_upload_project.py")
            print("  scripts\\stage3_render_upload.py")
            print("  scripts\\tubeharbor_render_upload.py")
            return 2
        return run_python_script(script, rest)

    print(f"Unknown tubeharbor command: {action}")
    return 2


def main(argv: list[str]) -> int:
    os.chdir(ROOT)
    src = str(ROOT / "src")
    old_pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = src + (os.pathsep + old_pythonpath if old_pythonpath else "")

    if not argv:
        return print_help()

    command, rest = argv[0], argv[1:]

    if command == "renderer":
        return renderer(rest)
    if command == "webeditor":
        return webeditor(rest)
    if command == "tubeharbor":
        return tubeharbor(rest)

    return run_echoforge(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
