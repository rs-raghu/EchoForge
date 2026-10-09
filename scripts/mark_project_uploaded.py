from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from echoforge.core.storage import read_json, atomic_json
from echoforge.core.project_state import mark_uploaded
from echoforge.stages.tubeharbor import upload_db


def main():
    parser=argparse.ArgumentParser(description='Reconcile a known remote upload without inserting another video.')
    parser.add_argument('--project',required=True)
    parser.add_argument('--video-id',default='')
    parser.add_argument('--url',default='')
    args=parser.parse_args(); project=Path(args.project)
    if not project.is_absolute(): project=ROOT/project
    report=read_json(project/'upload/youtube_upload_report.json',{})
    vid=args.video_id or (report.get('video_id') if report.get('ok') else '')
    if not vid: raise SystemExit('A successful upload report or explicit remote video ID is required')
    result={**report,'ok':True,'status':'uploaded','video_id':vid,'url':args.url or f'https://www.youtube.com/watch?v={vid}'}
    upload_db.record_upload(project,result)
    atomic_json(project/'upload/youtube_upload_report.json',result)
    state=mark_uploaded(project,result)
    print(json.dumps({'ok':True,'video_id':vid,'project_id':state.get('project_id',project.name)},indent=2))
    return 0


if __name__=='__main__': raise SystemExit(main())
