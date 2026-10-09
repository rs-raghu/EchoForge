from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from echoforge.core.storage import read_json
from echoforge.stages.renderer.render_jobs import start_render_upload_job


def main():
    parser=argparse.ArgumentParser(description='Render and optionally upload using the shared durable job service.')
    parser.add_argument('--project', required=True)
    parser.add_argument('--request')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--upload', action='store_true')
    group.add_argument('--no-upload', action='store_true')
    parser.add_argument('--visibility', choices=['private','public','unlisted','schedule'], default=None)
    parser.add_argument('--schedule-at', '--schedule-time', dest='scheduleAt')
    for name in ['title','description','tags','category-id']:
        parser.add_argument('--' + name, default=None)
    parser.add_argument('--fps', type=int, default=None)
    parser.add_argument('--crf', type=int, default=None)
    args=parser.parse_args()
    project=Path(args.project)
    if not project.is_absolute(): project=ROOT / project
    options=read_json(Path(args.request), {}) if args.request else {}
    options.update({k:v for k,v in vars(args).items() if v is not None and k not in {'project','request','upload','no_upload'}})
    if args.upload: options['upload']=True
    if args.no_upload: options['upload']=False
    result=start_render_upload_job(project, options, background=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get('ok') and result.get('status') == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
