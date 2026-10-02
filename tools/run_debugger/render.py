"""Analyze one run and write its replay to run_analysis/SR<n>_<YYYYMMDD_HHMMSS>.html (or .mp4)

    uv run python render.py SR45                # scrubbable HTML page (default)
    uv run python render.py SR45 --video        # Manim video, 480p
    uv run python render.py SR45 --video h      # Manim video, 1080p
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUALITY = {"l": "480p15", "m": "720p30", "h": "1080p60"}

args = sys.argv[1:]
run = args[0]
video = "--video" in args
q = next((a for a in args[1:] if a in QUALITY), "l")

subprocess.run([sys.executable, "analyze.py", run], cwd=HERE, check=True)
dest_dir = HERE / "run_analysis"
dest_dir.mkdir(exist_ok=True)
stamp = f"{run}_{datetime.now():%Y%m%d_%H%M%S}"

if video:
    env = {**os.environ, "RUN": run, "PYTHONWARNINGS": "ignore"}
    subprocess.run(["manim", f"-q{q}", "replay.py", "RunReplay"], cwd=HERE, env=env, check=True)
    dest = dest_dir / f"{stamp}.mp4"
    shutil.copy2(HERE / "media/videos/replay" / QUALITY[q] / "RunReplay.mp4", dest)
else:
    data = (HERE / f"out/{run}.json").read_text(encoding="utf8")
    data = json.dumps(json.loads(data)).replace("</", "<\\/")   # safe inside <script>
    page = (HERE / "page.html").read_text(encoding="utf8")
    page = page.replace("/*DATA*/", data).replace("<title>Run Replay</title>", f"<title>{run} Replay</title>")
    dest = dest_dir / f"{stamp}.html"
    dest.write_text(page, encoding="utf8")
print(f"OUTPUT: {dest}")
