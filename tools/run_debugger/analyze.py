"""Flag wasteful LLM calls in one sim run and lay them on a real-time timeline. Writes JSON.

    uv run python analyze.py SR65            # -> out/SR65.json

Flags (facts only; one decision row = one decide API call):
  retry      result_status is not "success", or the row carries an error
  redundant  same agent repeats the same action + intent + cell, or a near-identical thought
  loop       agent returns to a cell it left within the last LOOP_WINDOW decisions

Timeline (seconds from the first log line of the run). ASSUMPTION: a decision row is logged
when its action finishes, so the cycle is rebuilt backwards from the timestamp:
  look  = observe_ms   (screenshot + senses)
  think = llm_ms       (the decide API call)
  act   = act_ms       (command sent to Unreal)
  after = walking (walk_to) or waiting, until the next look starts.

Every model call (wake / decide / ask / chat / vision) is in api_calls/SR<n>.jsonl for runs from
2026-10-02 on. Older runs: wake-ups come from sim_runner.log, latest run only.
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

LOGS = Path(__file__).resolve().parents[2] / "Python/worlds/MCP_World/logs"
LOG = LOGS / "agent_decisions.log"
RUNNER_LOG = LOGS / "sim_runner.log"
API_DIR = LOGS / "api_calls"            # one SR<n>.jsonl per run
LOOP_WINDOW = 6
SIMILAR = 0.85
EVENTS = {"interrupt_activated", "interrupt_resolved", "survey_heading"}
_RUNNER_RE = re.compile(r"^(\S+ \S+) \w+ \[(SR\d+)\] \[(\w+)\] (\S+) (woke up|decided):")


def load(run: str, log: Path = LOG) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """(decision rows, event rows) per agent."""
    decisions: dict[str, list[dict]] = {}
    events: dict[str, list[dict]] = {}
    for line in log.read_text(encoding="utf8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("sim_run") != run:
            continue
        if d.get("action_type"):
            decisions.setdefault(d["agent_id"], []).append(d)
        elif d.get("event") in EVENTS:
            events.setdefault(d["agent_id"], []).append(d)
    return decisions, events


def load_runner(run: str) -> list[dict]:
    """Model calls named in sim_runner.log (only present if this is the latest run)."""
    if not RUNNER_LOG.exists():
        return []
    out = []
    for line in RUNNER_LOG.read_text(encoding="utf8", errors="replace").splitlines():
        m = _RUNNER_RE.match(line)
        if m and m.group(2) == run:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f").astimezone()
            out.append({"ts": ts, "agent": m.group(3), "model": m.group(4), "kind": m.group(5)})
    return out


def load_api(run: str) -> list[dict]:
    """Every model call of the run from api_calls/SR<n>.jsonl (runs before 2026-10-02 have none)."""
    path = API_DIR / f"{run}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("sim_run") == run:
            d["ts"] = datetime.fromisoformat(d["timestamp"])
            out.append(d)
    return out


def _flag(prev: list[dict], d: dict) -> tuple[str, str] | tuple[None, None]:
    if d.get("result_status") != "success" or d.get("error"):
        why = f'result was "{d.get("result_status")}"'
        return "retry", why + (f': {str(d["error"])[:80]}' if d.get("error") else "")
    if prev:
        p = prev[-1]
        key = lambda x: (x["action_type"], (x.get("move") or {}).get("intent"), x.get("cell"))
        ratio = difflib.SequenceMatcher(None, p.get("thought", ""), d.get("thought", "")).ratio()
        if key(p) == key(d):
            return "redundant", f'same action ({d["action_type"]}), direction and cell {d.get("cell")} as the call before'
        if ratio >= SIMILAR:
            return "redundant", f"thought is {ratio:.0%} the same as the call before"
    cells = [x.get("cell") for x in prev[-LOOP_WINDOW:]]
    if cells and d.get("cell") in cells and cells[-1] != d.get("cell"):
        ago = len(cells) - max(i for i, c in enumerate(cells) if c == d.get("cell"))
        return "loop", f'back in cell {d.get("cell")}, last there {ago} calls ago'
    return None, None


def _event_label(e: dict) -> tuple[str, str]:
    if e["event"] == "survey_heading":
        sp = e["survey_progress"]
        return "survey", f'survey look {sp["heading"]} at cell {sp["col"]},{sp["row"]}: {sp["status"]}'
    it = e["interrupt"]
    verb = "started" if e["event"] == "interrupt_activated" else "ended"
    return "interrupt", f'{it["kind"]} interrupt {verb}: {it["reason"]}'


def analyze(run: str) -> dict:
    decisions, events = load(run)
    runner = load_runner(run)
    api = load_api(run)
    stamps = [datetime.fromisoformat(d["timestamp"]) for rows in (*decisions.values(), *events.values()) for d in rows]
    t0 = min(stamps + [r["ts"] for r in runner] + [a["ts"] for a in api]) if stamps else None
    sec = lambda ts: round((ts - t0).total_seconds(), 2)

    models = {r["model"] for r in runner} | {f'{a["provider"]}/{a["model"]}' for a in api}
    out = {"run": run, "models": sorted(models), "has_api_log": bool(api), "agents": {}}
    for agent in sorted(set(decisions) | set(events) | {a["agent_id"] for a in api if a.get("agent_id")}):
        rows = decisions.get(agent, [])
        calls = []
        for i, d in enumerate(rows):
            flag, reason = _flag(rows[:i], d)
            t = d.get("timing") or {}
            end = sec(datetime.fromisoformat(d["timestamp"]))
            act, think, look = (t.get("act_ms") or 0) / 1000, (t.get("llm_ms") or 0) / 1000, (t.get("observe_ms") or 0) / 1000
            calls.append({
                "i": i,
                "time": d["timestamp"][11:19],
                "action": d["action_type"],
                "cell": d.get("cell"),
                "thought": d.get("thought", ""),
                "llm_ms": t.get("llm_ms", 0) or 0,
                "flag": flag,
                "reason": reason,
                "look": [round(end - act - think - look, 2), round(end - act - think, 2)],
                "think": [round(end - act - think, 2), round(end - act, 2)],
                "act": [round(end - act, 2), end],
                "moved_cm": d.get("moved_cm") or 0,
            })
        flagged = [c for c in calls if c["flag"]]
        evs = []
        for e in events.get(agent, []):
            kind, text = _event_label(e)
            evs.append({"t": sec(datetime.fromisoformat(e["timestamp"])), "kind": kind, "text": text})
        wakes = [{"t": sec(r["ts"]), "model": r["model"]} for r in runner if r["agent"] == agent and r["kind"] == "woke up"]
        apis = [{"t": sec(a["ts"]), "dur": round((a.get("ms") or 0) / 1000, 2), "purpose": a["purpose"],
                 "model": f'{a["provider"]}/{a["model"]}', "ok": a["ok"], "error": a.get("error"),
                 "tokens_in": a.get("input_tokens"), "tokens_out": a.get("output_tokens")}
                for a in api if a.get("agent_id") == agent]
        out["agents"][agent] = {
            "calls": calls,
            "api": apis,
            "events": evs,
            "wakes": wakes,
            "counts": {k: sum(c["flag"] == k for c in calls) for k in ("retry", "redundant", "loop")},
            "wasted_s": round(sum(c["llm_ms"] for c in flagged) / 1000, 1),
            "total_s": round(sum(c["llm_ms"] for c in calls) / 1000, 1),
        }
    ends = [c["act"][1] for a in out["agents"].values() for c in a["calls"]] + \
           [e["t"] for a in out["agents"].values() for e in a["events"]] +            [x["t"] + x["dur"] for a in out["agents"].values() for x in a["api"]]
    out["duration_s"] = max(ends, default=0)
    return out


if __name__ == "__main__":
    run = sys.argv[1]
    result = analyze(run)
    if not result["agents"]:
        sys.exit(f"No decision rows for {run} in {LOG}")
    Path("out").mkdir(exist_ok=True)
    Path(f"out/{run}.json").write_text(json.dumps(result, indent=1), encoding="utf8")
    print(f'{run}: {result["duration_s"]:.0f}s, models: {result["models"] or "not in sim_runner.log"}')
    for a, v in result["agents"].items():
        print(a, len(v["calls"]), "calls", v["counts"], f'{v["wasted_s"]}s of {v["total_s"]}s wasted',
              len(v["events"]), "events", len(v["wakes"]), "wake calls", len(v["api"]), "logged API calls")
