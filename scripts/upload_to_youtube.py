from pathlib import Path
import sys
ROOT_DIR=Path(__file__).resolve().parents[1]
SRC_DIR=ROOT_DIR/"src"
if str(SRC_DIR) not in sys.path: sys.path.insert(0,str(SRC_DIR))
from echoforge.stages.tubeharbor.youtube_uploader import upload_to_youtube
import argparse,json
p=argparse.ArgumentParser(); p.add_argument("--project",required=True); p.add_argument("--video",required=True); p.add_argument("--visibility",default="private"); p.add_argument("--schedule-at"); p.add_argument("--title"); p.add_argument("--description"); p.add_argument("--tags"); a=p.parse_args()
print(json.dumps(upload_to_youtube(a.video,a.project,{"visibility":a.visibility,"scheduleAt":a.schedule_at,"title":a.title,"description":a.description,"tags":a.tags},lambda x: print(x.get("message",x),flush=True)),indent=2,ensure_ascii=False))
