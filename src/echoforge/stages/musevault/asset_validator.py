from __future__ import annotations

import json
from echoforge.stages.musevault.image_service import validate_musevault_assets


def validate_assets_report() -> dict:
    return validate_musevault_assets()


def print_assets_report() -> int:
    report = validate_assets_report()
    print(json.dumps(report, indent=2))
    return 0 if report.get('ok') else 1
