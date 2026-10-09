from pathlib import Path
import sys,json,argparse
ROOT_DIR=Path(__file__).resolve().parents[1]
SRC_DIR=ROOT_DIR/"src"
if str(SRC_DIR) not in sys.path: sys.path.insert(0,str(SRC_DIR))
from echoforge.stages.renderer.exporter import export_editor_project
from echoforge.stages.tubeharbor.youtube_uploader import upload_to_youtube
p=argparse.ArgumentParser(); p.add_argument("--project",required=True); p.add_argument("--visibility",default=None); p.add_argument("--schedule-at"); p.add_argument("--title"); p.add_argument("--description"); p.add_argument("--tags"); p.add_argument("--fps",type=int,default=24); p.add_argument("--render-only",action="store_true"); a=p.parse_args()
cb=lambda x: print(x.get("message",x),flush=True)
r=export_editor_project(a.project,fps=a.fps,progress_callback=cb)
res={"ok":bool(r.get("ok")),"render":r}
if r.get("ok") and not a.render_only: res["upload"]=upload_to_youtube(r["output"],a.project,{"visibility":a.visibility,"scheduleAt":a.schedule_at,"title":a.title,"description":a.description,"tags":a.tags},cb); res["ok"]=bool(res["upload"].get("ok"))
print(json.dumps(res,indent=2,ensure_ascii=False))
