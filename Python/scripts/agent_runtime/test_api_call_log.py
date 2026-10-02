"""Offline tests for the per-run API call log and its prompt capture.

Every model call writes one line to ``api_calls/SR<n>.jsonl``; a call that
noted its prompt also writes ``api_calls/prompts/SR<n>/<seq>_<agent>_<purpose>.json``
(the prompt lab replays these). No network. Run:
    .venv\\Scripts\\python.exe scripts\\agent_runtime\\test_api_call_log.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # Python/
sys.path.insert(0, str(ROOT))

from agent_runtime import api_call_log, sim_run   # noqa: E402


def check(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"ok: {label}")


def _lines(logs: Path, run: str) -> list[dict]:
    return [json.loads(x) for x in (logs / "api_calls" / f"{run}.jsonl").read_text(
        encoding="utf-8").splitlines()]


def test_line_and_prompt_file():
    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp)
        api_call_log.set_dir(logs)
        sim_run.set_active_run("SR70_P")
        with api_call_log.track("decide", "dufus", "openrouter", "qwen/qwen3.7-flash"):
            api_call_log.note_usage(6400, 150)
            api_call_log.note_prompt("SYSTEM TEXT", "USER TEXT", None)
            api_call_log.note_response('{"action": {"type": "idle"}}')
        line = _lines(logs, "SR70_P")[-1]
        check("the line carries purpose, agent and tokens",
              line["purpose"] == "decide" and line["agent_id"] == "dufus"
              and line["input_tokens"] == 6400 and line["ok"] is True)
        check("the line does not carry the prompt text itself",
              "_prompt" not in line and "_response" not in line and "USER TEXT" not in json.dumps(line))
        side = logs / "api_calls" / line["prompt_file"]
        check("the line points at a prompt file that exists", side.is_file())
        data = json.loads(side.read_text(encoding="utf-8"))
        check("the prompt file has system, user, image and the raw answer",
              data["system"] == "SYSTEM TEXT" and data["user"] == "USER TEXT"
              and data["image"] is None and data["response"] == '{"action": {"type": "idle"}}')
        check("the prompt file names run, agent and model",
              data["sim_run"] == "SR70_P" and data["agent_id"] == "dufus"
              and data["model"] == "qwen/qwen3.7-flash")

        with api_call_log.track("vision", "maren", "openrouter", "qwen/qwen3.7-flash"):
            pass
        check("a call that noted no prompt writes no prompt file",
              "prompt_file" not in _lines(logs, "SR70_P")[-1])
        check("no cost reported -> no cost field (never a guessed 0)",
              "cost_usd" not in _lines(logs, "SR70_P")[-1])

        with api_call_log.track("decide", "dufus", "openrouter", "qwen/qwen3.7-flash"):
            api_call_log.note_usage(6400, 150, 0.000211)
        check("a provider-reported cost lands on the line",
              _lines(logs, "SR70_P")[-1]["cost_usd"] == 0.000211)


def test_failed_call_still_saves_its_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp)
        api_call_log.set_dir(logs)
        sim_run.set_active_run("SR71_P")
        try:
            with api_call_log.track("wake", "maren", "openrouter", "qwen/qwen3.7-flash"):
                api_call_log.note_prompt("S", "U", None)
                raise RuntimeError("openrouter 429")
        except RuntimeError:
            pass
        line = _lines(logs, "SR71_P")[-1]
        check("a failed call is logged as failed", line["ok"] is False and "429" in line["error"])
        data = json.loads((logs / "api_calls" / line["prompt_file"]).read_text(encoding="utf-8"))
        check("and its prompt is still saved (so the failure can be replayed)",
              data["user"] == "U" and data["response"] is None and data["ok"] is False)


def test_only_the_newest_prompt_runs_are_kept():
    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp)
        api_call_log.set_dir(logs)
        saved = api_call_log.KEEP_PROMPT_RUNS
        api_call_log.KEEP_PROMPT_RUNS = 2
        try:
            for run in ("SR9", "SR10_S", "SR11_P"):
                sim_run.set_active_run(run)
                with api_call_log.track("decide", "dufus", "openrouter", "m"):
                    api_call_log.note_prompt("S", "U", None)
        finally:
            api_call_log.KEEP_PROMPT_RUNS = saved
        left = sorted(d.name for d in (logs / "api_calls" / "prompts").iterdir())
        check("prompt folders beyond the newest 2 runs are deleted, oldest first",
              left == ["SR10_S", "SR11_P"])
        check("the jsonl lines themselves are not pruned by prompt pruning",
              (logs / "api_calls" / "SR9.jsonl").is_file())


def main():
    test_line_and_prompt_file()
    test_failed_call_still_saves_its_prompt()
    test_only_the_newest_prompt_runs_are_kept()
    print("\nAll api-call-log checks passed.")


if __name__ == "__main__":
    main()
