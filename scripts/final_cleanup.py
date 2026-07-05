from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def candidates(remove_backups: bool) -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("__pycache__"):
        out.append(p)
    for pat in ("*.pyc", "*.pyo", ".DS_Store", "Thumbs.db"):
        out.extend(ROOT.rglob(pat))
    out.extend([ROOT / ".pytest_cache"])
    if remove_backups:
        out.extend([ROOT / ".migration_backups"])
    return [p for p in out if p.exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Clean safe temporary files from EF_CLEAN.")
    ap.add_argument("--apply", action="store_true", help="Actually delete files. Without this, only prints what would be removed.")
    ap.add_argument("--remove-backups", action="store_true", help="Also remove .migration_backups. Use only after you are sure everything works.")
    args = ap.parse_args()
    items = candidates(args.remove_backups)
    print(f"Found {len(items)} cleanup item(s).")
    for p in items:
        print(("DELETE " if args.apply else "WOULD DELETE ") + str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p))
    if args.apply:
        for p in items:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
        print("Cleanup complete.")
    else:
        print("Dry run only. Rerun with --apply to delete these safe temporary files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
