"""check_win.py から起動される補助プロセス。合図のファイルができるまで待ってから動く。"""
import json
import subprocess
import sys
import time
from pathlib import Path


def wait_for(p: Path, sec: float = 30) -> None:
    t = time.time()
    while not p.exists():
        if time.time() - t > sec:
            sys.exit(2)
        time.sleep(0.1)


mode, go, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
wait_for(go)
if mode == "breakaway":
    res = {}
    try:
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             creationflags=0x01000000 | 0x00000008)  # BREAKAWAY_FROM_JOB | DETACHED_PROCESS
        res["ok"] = True
        res["grandchild"] = p.pid
    except OSError as e:
        res["ok"] = False
        res["winerror"] = getattr(e, "winerror", None)
        res["error"] = str(e)[:200]
    out.write_text(json.dumps(res), encoding="utf-8")
elif mode == "tree":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    out.write_text(json.dumps({"child": child.pid}), encoding="utf-8")
    time.sleep(120)
