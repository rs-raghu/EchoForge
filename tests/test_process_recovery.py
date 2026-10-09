import os
import subprocess
import sys
from pathlib import Path
from echoforge.core.storage import file_lock

ROOT=Path(__file__).resolve().parents[1]


def test_two_processes_refresh_once(tmp_path):
    script="""
import sys,time
from pathlib import Path
from echoforge.stages.songscout import database as db, refresh
root=Path(sys.argv[1]); db.SONGSCOUT_DB_PATH=root/'songs.sqlite3'; refresh.SONGSCOUT_DATA_DIR=root
def scrape(**kw):
    with (root/'calls.txt').open('a') as f: f.write('fetch\\n')
    time.sleep(.2)
    return [{'lines':['1','Fixture','Singer']}]
refresh.scrape_youtube_charts=scrape
refresh.delete_transient_debug_files=lambda:None
refresh.refresh_chart()
"""
    env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
    workers=[subprocess.Popen([sys.executable,'-c',script,str(tmp_path)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
    try:
        for worker in workers:
            out,err=worker.communicate(timeout=20)
            assert worker.returncode==0,err.decode()
        assert (tmp_path/'calls.txt').read_text().splitlines()==['fetch']
    finally:
        for worker in workers:
            if worker.poll() is None: worker.kill(); worker.wait()


def test_os_releases_lock_after_interruption(tmp_path):
    script="""
import sys,time
from pathlib import Path
from echoforge.core.storage import file_lock
root=Path(sys.argv[1])
with file_lock(root/'worker.lock'):
    print('locked',flush=True)
    time.sleep(30)
"""
    worker=subprocess.Popen([sys.executable,'-c',script,str(tmp_path)],env={**os.environ,'PYTHONPATH':str(ROOT/'src')},stdout=subprocess.PIPE)
    try:
        assert worker.stdout.readline().strip()==b'locked'
        worker.terminate(); worker.wait(timeout=5)
        with file_lock(tmp_path/'worker.lock',timeout=1): pass
    finally:
        if worker.poll() is None: worker.kill(); worker.wait()
        worker.stdout.close()
