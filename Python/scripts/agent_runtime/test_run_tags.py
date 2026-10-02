"""Offline tests for run tags that carry the sim mode: SR<n>_P / SR<n>_S (2026-10-02).

Old bare tags (SR45) must keep working, and everything that sorts runs must
read the number, not cut ``tag[2:]`` (which made "66_P" crash the replay list
and made the API-log prune delete the NEWEST run first). Run:
    .venv\\Scripts\\python.exe scripts\\agent_runtime\\test_run_tags.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # Python/
sys.path.insert(0, str(ROOT))

from agent_runtime import api_call_log, run_replay, sim_run   # noqa: E402


def check(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"ok: {label}")


def test_format_and_allocate():
    check("play -> SR66_P", sim_run.format_run(66, "play") == "SR66_P")
    check("survey -> SR67_S", sim_run.format_run(67, "survey") == "SR67_S")
    check("mode is case/space tolerant", sim_run.format_run(3, " Play ") == "SR3_P")
    check("no / unknown mode -> bare tag", sim_run.format_run(5) == "SR5"
          and sim_run.format_run(5, "dance") == "SR5")
    with tempfile.TemporaryDirectory() as tmp:
        world = Path(tmp)
        check("first play run", sim_run.allocate_run(world, "play") == "SR1_P")
        check("one counter across modes", sim_run.allocate_run(world, "survey") == "SR2_S")
        check("current_run keeps the last mode", sim_run.current_run(world) == "SR2_S")
        check("mode persisted", json.loads((world / "sim_run.json").read_text())["mode"] == "survey")


def test_run_number():
    check("SR66_P -> 66", sim_run.run_number("SR66_P") == 66)
    check("SR45 -> 45 (old bare tag)", sim_run.run_number("SR45") == 45)
    check("junk -> -1", sim_run.run_number("observation") == -1 and sim_run.run_number(None) == -1)


def test_api_log_prune_keeps_the_newest():
    with tempfile.TemporaryDirectory() as tmp:
        api_call_log.set_dir(Path(tmp))
        d = Path(tmp) / "api_calls"
        d.mkdir()
        for name in ("SR9.jsonl", "SR10_S.jsonl", "SR66_P.jsonl"):
            (d / name).write_text("{}\n", encoding="utf-8")
        saved = api_call_log.KEEP_RUNS
        api_call_log.KEEP_RUNS = 2
        try:
            api_call_log._prune()
        finally:
            api_call_log.KEEP_RUNS = saved
        left = sorted(p.name for p in d.iterdir())
        check("the oldest (SR9) is deleted, the newest (SR66_P) kept",
              left == ["SR10_S.jsonl", "SR66_P.jsonl"])


def test_replay_frames_and_sorting():
    check("SR66_P frame accepted",
          run_replay.is_frame_name("SR66_P_observation_20261002_134000.png"))
    check("SR67_S frame with a tag accepted",
          run_replay.is_frame_name("SR67_S_observation_20261002_134000_wake_N.png"))
    check("old SR45 frame accepted", run_replay.is_frame_name("SR45_observation_20260801_120000.png"))
    check("an unknown mode letter is rejected",
          not run_replay.is_frame_name("SR66_X_observation_20261002_134000.png"))
    with tempfile.TemporaryDirectory() as tmp:
        obs = Path(tmp) / "agents" / "dufus" / "observations"
        obs.mkdir(parents=True)
        for name in ("SR9_observation_20260801_120000.png",
                     "SR66_P_observation_20261002_134000.png",
                     "SR10_S_observation_20260901_120000.png"):
            (obs / name).write_bytes(b"\x89PNG fake")
        check("runs sort by number, newest first, across old and new tags",
              run_replay.list_runs(Path(tmp)) == ["SR66_P", "SR10_S", "SR9"])


def test_run_debugger_reads_new_tags():
    path = ROOT.parent / "tools" / "run_debugger" / "analyze.py"
    spec = importlib.util.spec_from_file_location("rd_analyze", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    line = ("2026-10-02 13:49:28,264 INFO [SR66_P] [dufus] "
            "openrouter/qwen/qwen3.7-flash decided: speak_to - hi")
    m = mod._RUNNER_RE.match(line)
    check("run debugger parses [SR66_P] runner lines", m is not None and m.group(2) == "SR66_P")
    old = "2026-08-01 10:00:00,000 INFO [SR45] [dufus] anthropic/haiku decided: idle - x"
    check("and still parses old [SR45] lines", mod._RUNNER_RE.match(old).group(2) == "SR45")


def main():
    test_format_and_allocate()
    test_run_number()
    test_api_log_prune_keeps_the_newest()
    test_replay_frames_and_sorting()
    test_run_debugger_reads_new_tags()
    print("\nAll run-tag checks passed.")


if __name__ == "__main__":
    main()
