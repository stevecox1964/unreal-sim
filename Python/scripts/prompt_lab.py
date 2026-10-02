"""Prompt lab — test a hypothesis about the decision prompt on the real model.

Builds Dufus's (or Maren's) real decision prompt — their real character,
goals, rules, doctrine and actions, plus a scene rebuilt from a live run —
changes ONE thing, asks the configured model N times per variant, and counts
which actions it picks. OpenRouter cost is pennies per experiment.

    .venv\\Scripts\\python.exe scripts\\prompt_lab.py list
    .venv\\Scripts\\python.exe scripts\\prompt_lab.py run phantom_maren -n 10
    .venv\\Scripts\\python.exe scripts\\prompt_lab.py show phantom_maren   # print the prompts, no calls
    .venv\\Scripts\\python.exe scripts\\prompt_lab.py replay <prompt_file.json> -n 10

Results go to scripts/prompt_lab_results/<experiment>_<YYYYMMDD_HHMMSS>.json.
Uses the same provider/model as the sim (LLM_PROVIDER / LLM_MODEL in .env);
only OpenRouter is wired here.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import copy
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

PY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PY))

from agent_runtime import llm_router                     # noqa: E402
from agent_runtime.agent import Agent                     # noqa: E402
from agent_runtime.place_db import PlaceDB                # noqa: E402
from agent_runtime.world_grid import WorldGrid            # noqa: E402

WORLD = PY / "worlds" / "MCP_World"
RESULTS = Path(__file__).resolve().parent / "prompt_lab_results"
PARALLEL = 4


# ── Prompt building ───────────────────────────────────────────────────────────

def _place_context(name: str) -> dict | None:
    """The real PlaceDB record for a named place, read from a temp copy."""
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "world_places.db"
        shutil.copy2(WORLD / "world_places.db", db_copy)
        db = PlaceDB(db_copy)
        cell = db.find_named_cell(name)
        return db.get_place(*cell) if cell else None


def build_prompt(agent_id: str, observation: dict, memories: list[dict],
                 doctrine: bool = True) -> tuple[str, str]:
    """(system, user) exactly as LLMRouter.decide renders them — no call made.
    ``doctrine=False`` keeps only the agent's own rules (no @import files)."""
    agent = Agent.load(WORLD / "agents", agent_id)
    if not doctrine:
        own = (WORLD / "agents" / agent_id / "rules.md").read_text(encoding="utf-8")
        agent.rules_text = "\n".join(ln for ln in own.splitlines()
                                     if not ln.startswith("@import"))
    router = llm_router.LLMRouter()
    captured = {}

    def capture(model, system_text, user_text, image_path=None, json_mode=True):
        captured.update(system=system_text, user=user_text)
        return '{"action": {"type": "idle"}, "thought_summary": "capture"}'

    router._decide_openrouter = capture
    router._decide_anthropic = lambda model, system_text, user_text, image_path=None: capture(
        model, system_text, user_text)
    router.decide(agent, observation, memories)
    if not captured:
        sys.exit("prompt was not built (no API key / provider configured?)")
    return captured["system"], captured["user"]


def _drop_section(user: str, heading: str) -> str:
    """Remove one '## heading' section (up to the next '## ')."""
    return re.sub(rf"## {re.escape(heading)}.*?(?=\n## |\Z)", "", user, flags=re.S)


def _drop_actions(system: str, actions: list[str]) -> str:
    """Remove allowed-action lines that start with a JSON schema of those types."""
    keep = []
    for line in system.splitlines():
        if any(f'"type": "{a}"' in line for a in actions):
            continue
        keep.append(line)
    return "\n".join(keep)


# ── Scenes (rebuilt from SR66_P) ──────────────────────────────────────────────

def _scene_village_square(characters: list[dict], caption: str,
                          nearby: list[dict] | None = None) -> dict:
    """Dufus at the village square, 13:49 in SR66_P: settled there by his
    schedule, Maren really 72 m away at her truck."""
    grid = WorldGrid.load(WORLD / "world_grid.json")
    x, y = -1540.7, -848.4
    return {
        "location": {"x": x, "y": y, "z": 90.0},
        "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
        "grid": grid.locate(x, y),
        "place_context": _place_context("village square"),
        "world_time": "Day 1, 10:05",
        "current_action": "idle",
        "known_characters": ["Maren"],
        "nearby_characters": nearby or [],
        "seen": {
            "caption": caption,
            "characters": characters,
            "landmarks": [{"label": "American Bank building", "bearing": "left",
                           "distance": "mid", "confidence": 0.9},
                          {"label": "American flag", "bearing": "center",
                           "distance": "mid", "confidence": 0.9}],
            "footing": "pavement", "ground_ahead": "pavement", "path_ahead": "open",
        },
        "schedule": {"status": "act", "place": "village square",
                     "intent": "hang around the village square and chat with whoever turns up",
                     "block": {"start": "10:00", "end": "12:00", "place": "village square",
                               "activity": "hang around the village square"}},
    }


_FIGURES = [{"label": "unknown person", "bearing": "left", "distance": "mid", "confidence": 0.8},
            {"label": "unknown person", "bearing": "left", "distance": "mid", "confidence": 0.8}]
_MEMORIES = [{"importance": 0.6, "text": "Said good morning to Maren at the vegetable truck.",
              "timestamp": "2026-10-02T18:38:00"}]


def exp_phantom_maren():
    """H: the vision model naming a far figure "Maren" made Dufus greet her
    (SR66_P 13:49). Old eyes vs new eyes, same scene, Maren really 72 m away."""
    old = _scene_village_square(
        [{"label": "Maren", "bearing": "center", "distance": "near", "confidence": 0.95}] + _FIGURES,
        "The NPC stands on the sidewalk near the bank, facing Maren who is in the street ahead.")
    new = _scene_village_square(
        [{"label": "unknown person", "bearing": "center", "distance": "near",
          "confidence": 0.95}] + _FIGURES,
        "The NPC stands on the sidewalk near the bank, facing a person in the street ahead.")
    return {"old eyes (VLM says Maren)": build_prompt("dufus", old, _MEMORIES),
            "new eyes (unknown person)": build_prompt("dufus", new, _MEMORIES)}


def exp_survey_trim():
    """H: the survey-era parts of a Play prompt (wider map, cell survey state,
    neighbouring grid cells, refuse/allow_cell) do not change Play choices —
    so they can be cut to save tokens. Same scene, full vs trimmed."""
    scene = _scene_village_square(
        _FIGURES, "A quiet square with a bank and a flag; two people stand to the left.")
    system, user = build_prompt("dufus", scene, _MEMORIES)
    trimmed_user = user
    for heading in ("The Wider Map", "Survey State Of The Cell You Are Standing In",
                    "Where You Can Go Next"):
        trimmed_user = _drop_section(trimmed_user, heading)
    trimmed_system = _drop_actions(system, ["refuse_cell", "allow_cell"])
    return {"full prompt": (system, user), "survey parts cut": (trimmed_system, trimmed_user)}


def exp_close_maren():
    """H: with Maren truly within reach (2 m, engine-recognised), Dufus talks
    to her — the 'someone came close' path works for a real APC."""
    scene = _scene_village_square(
        [{"label": "Maren", "bearing": "center", "distance": "near", "distance_cm": 200.0,
          "confidence": 1.0, "source": "engine"}] + _FIGURES,
        "A person stands right in front of the NPC on the square.",
        nearby=[{"name": "Maren", "distance_cm": 200.0}])
    return {"Maren 2 m away": build_prompt("dufus", scene, _MEMORIES)}


def _talk_job(system: str, user: str) -> tuple[str, str]:
    """Cut what a talk decision does not need: walking/obstacle advice, the map
    sections, and the survey actions (the doctrine files are dropped by
    build_prompt(doctrine=False))."""
    user = re.sub(r"There are two kinds of direction.*?(?=If nothing is scheduled right now)",
                  "", user, flags=re.S)
    for heading in ("The Wider Map", "Survey State Of The Cell You Are Standing In",
                    "Where You Can Go Next"):
        user = _drop_section(user, heading)
    return _drop_actions(system, ["refuse_cell", "allow_cell"]), user


def exp_talk_split():
    """H: a talk-only prompt (no movement doctrine, no walking/obstacle advice,
    no map sections) makes the same choice when Maren is 2 m away and when a
    stranger is in view — so splitting the prompt by job is safe here."""
    out = {}
    close = _scene_village_square(
        [{"label": "Maren", "bearing": "center", "distance": "near", "distance_cm": 200.0,
          "confidence": 1.0, "source": "engine"}] + _FIGURES,
        "A person stands right in front of the NPC on the square.",
        nearby=[{"name": "Maren", "distance_cm": 200.0}])
    heard = copy.deepcopy(close)
    heard["heard"] = [{"speaker": "Maren", "text": "Morning, Dufus. Any news from Don's?",
                       "world_time": "Day 1, 10:05", "distance_cm": 200.0}]
    for label, scene in (("Maren 2 m", close), ("Maren 2 m, she spoke", heard)):
        full = build_prompt("dufus", scene, _MEMORIES)
        out[f"{label} / full"] = full
        out[f"{label} / talk job"] = _talk_job(*build_prompt("dufus", scene, _MEMORIES,
                                                            doctrine=False))
    return out


def _no_roster(system: str, user: str) -> tuple[str, str]:
    """Drop the always-on name list and the rule that a matching figure IS that person."""
    user = _drop_section(user, "Characters You May Encounter")
    user = user.replace("; one matching\n\"Characters You May Encounter\" is that person.", ".")
    return system, user


def _no_coordinates(system: str, user: str) -> tuple[str, str]:
    """Drop the raw engine position line ("x=…, y=…, z=…")."""
    return system, re.sub(r"\nx=-?\d+, y=-?\d+, z=-?\d+", "", user)


def exp_roster_removal():
    """H: without the always-on name list (and its "a matching figure IS that
    person" rule) Dufus still greets the real Maren when the engine recognises
    her 2 m away, and no longer treats a stranger as someone he knows."""
    out = {}
    close = _scene_village_square(
        [{"label": "Maren", "bearing": "center", "distance": "near", "distance_cm": 200.0,
          "confidence": 1.0, "source": "engine"}] + _FIGURES,
        "A person stands right in front of the NPC on the square.",
        nearby=[{"name": "Maren", "distance_cm": 200.0}])
    stranger = _scene_village_square(
        _FIGURES, "A quiet square with a bank and a flag; two people stand to the left.")
    for label, scene in (("engine sees Maren 2 m", close), ("strangers only", stranger)):
        full = build_prompt("dufus", scene, _MEMORIES)
        out[f"{label} / with roster"] = full
        out[f"{label} / no roster"] = _no_roster(*full)
    return out


def exp_no_coordinates():
    """H: removing the raw engine coordinates ("x=…, y=…, z=…") does not change
    choices — the APC navigates by places, compass and sight, not numbers."""
    scene = _scene_village_square(
        _FIGURES, "A quiet square with a bank and a flag; two people stand to the left.")
    scene["schedule"] = {"status": "travel", "place": "Don's Donuts",
                         "intent": "walk to Don's Donuts for a coffee and a donut",
                         "block": {"start": "10:00", "end": "11:00", "place": "Don's Donuts",
                                   "activity": "coffee and a donut"}}
    full = build_prompt("dufus", scene, _MEMORIES)
    return {"travel / with x,y,z": full, "travel / no x,y,z": _no_coordinates(*full)}


def _real_context(x: float, y: float, places: int, episodes: int) -> dict:
    """Dufus's real long-run context: places (nearest first, from PlaceDB),
    the last N real episodes, and his real acquaintances."""
    import math
    from agent_runtime.place_db import yaw_to_compass
    grid = WorldGrid.load(WORLD / "world_grid.json")
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "world_places.db"
        shutil.copy2(WORLD / "world_places.db", db_copy)
        db = PlaceDB(db_copy)
        rows = []
        for p in db.all_named_places():
            c = grid.cell_center(p["col"], p["row"])
            if c:
                rows.append({"name": p["name"], "x": c[0], "y": c[1], "col": p["col"], "row": p["row"]})
        for o in db.all_owned_places():
            c = grid.cell_center(o["col"], o["row"])
            if c:
                rows.append({"name": o["name"], "x": c[0] + o["dx"], "y": c[1] + o["dy"],
                             "col": o["col"], "row": o["row"], "owner": o["owner"]})
    for r in rows:
        dx, dy = r["x"] - x, r["y"] - y
        r["bearing"] = yaw_to_compass(math.degrees(math.atan2(dy, dx)))
        r["distance_m"] = math.hypot(dx, dy) / 100.0
    agent_dir = WORLD / "agents" / "dufus"
    eps = [json.loads(ln) for ln in (agent_dir / "episodes.jsonl").read_text(
        encoding="utf-8").splitlines() if ln.strip()]
    social = json.loads((agent_dir / "social.json").read_text(encoding="utf-8"))["acquaintances"]
    people = sorted(social.values(), key=lambda p: (-p.get("meet_count", 0), p.get("name", "")))
    return {"known_places": sorted(rows, key=lambda r: r["distance_m"])[:places],
            "recent_episodes": eps[-episodes:], "acquaintances": people[:8]}


def _real_memories(n: int) -> list[dict]:
    """Dufus's real memories (30 on disk = the cap); above 30, older real
    episodes are rephrased as memories to simulate a raised cap."""
    agent_dir = WORLD / "agents" / "dufus"
    mem = json.loads((agent_dir / "memory.json").read_text(encoding="utf-8"))["memories"]
    if n <= len(mem):
        return mem[-n:]
    eps = [json.loads(ln) for ln in (agent_dir / "episodes.jsonl").read_text(
        encoding="utf-8").splitlines() if ln.strip()]
    extra = [{"importance": 0.5, "timestamp": f"2026-09-0{1 + i % 9}T00:00:{i % 60:02d}",
              "text": f"{e.get('world_time')}: at {e.get('place') or 'somewhere'} I did "
                      f"{e.get('action')}" + (f", saw {', '.join(e['saw'])}" if e.get("saw") else "")}
             for i, e in enumerate(eps[: n - len(mem)])]
    return extra + mem


def exp_context_stress():
    """H (user: "qwen may choke"): as the prompt fills with a long run's real
    context — memories at their cap of 30, 8 places, 5 past moments, people —
    and beyond (120 memories, 16 places, 20 moments), Qwen still picks the
    right action, returns valid JSON, and does not slow down badly. Two scenes
    with a clear right answer: travel to Don's Donuts; answer Maren 2 m away."""
    travel = _scene_village_square(
        _FIGURES, "A quiet square with a bank and a flag; two people stand to the left.")
    travel["schedule"] = {"status": "travel", "place": "Don's Donuts",
                          "intent": "walk to Don's Donuts for a coffee and a donut",
                          "block": {"start": "10:00", "end": "11:00", "place": "Don's Donuts",
                                    "activity": "coffee and a donut"}}
    talk = _scene_village_square(
        [{"label": "Maren", "bearing": "center", "distance": "near", "distance_cm": 200.0,
          "confidence": 1.0, "source": "engine"}] + _FIGURES,
        "A person stands right in front of the NPC on the square.",
        nearby=[{"name": "Maren", "distance_cm": 200.0}])
    talk["heard"] = [{"speaker": "Maren", "text": "Dufus! Can you carry a crate to the truck?",
                      "world_time": "Day 1, 10:05", "distance_cm": 200.0}]
    out = {}
    levels = (("fresh", 1, 0, 0), ("long run (caps)", 30, 8, 5), ("raised caps x4", 120, 16, 20))
    for scene_name, scene in (("travel", travel), ("talk", talk)):
        for level, n_mem, n_places, n_eps in levels:
            s = copy.deepcopy(scene)
            if n_places or n_eps:
                s.update(_real_context(-1540.7, -848.4, n_places, n_eps))
            out[f"{scene_name} / {level}"] = build_prompt("dufus", s, _real_memories(n_mem))
    return out


def exp_too_far_fact():
    """H: an accepted-but-did-nothing result ("Maren is 72 m away — too far to
    talk to; nothing was said") never reaches the brain today (only failures and
    movement do), so Dufus repeats speak_to into the void. Shown as a Sense
    line, he does something else (walks toward her or carries on)."""
    scene = _scene_village_square(
        _FIGURES, "A quiet square with a bank and a flag; two people stand to the left.")
    scene["schedule"] = {"status": "act", "place": "village square",
                         "intent": "find Maren and tell her the donut shop has a new flavour",
                         "block": {"start": "10:00", "end": "12:00", "place": "village square",
                                   "activity": "tell Maren the donut news"}}
    memories = _MEMORIES + [{"importance": 0.7, "timestamp": "2026-10-02T19:04:00",
                             "text": "I want to tell Maren the donut shop has a new flavour."}]
    system, user = build_prompt("dufus", scene, memories)
    line = ('Sense: your last action (speak_to Maren) did nothing — Maren is 72 m away, too far '
            'to talk to (you talk from within 3 m); nothing was said.\n')
    marker = "## Your Current State\n"
    told = user.replace(marker, marker + line, 1)
    assert told != user
    out = {"absent / no result fact (today)": (system, user),
           "absent / result fact shown": (system, told)}
    # The realistic case: Maren in view and in the nearby list at 10 m —
    # close enough to see, too far to talk.
    seen10 = copy.deepcopy(scene)
    seen10["seen"]["characters"] = [{"label": "Maren", "bearing": "center", "distance": "mid",
                                     "distance_cm": 1000.0, "confidence": 1.0,
                                     "source": "engine"}] + _FIGURES
    seen10["nearby_characters"] = [{"name": "Maren", "distance_cm": 1000.0}]
    s10, u10 = build_prompt("dufus", seen10, memories)
    out["Maren 10 m / no result fact (today)"] = (s10, u10)
    out["Maren 10 m / result fact shown"] = (s10, u10.replace(
        marker, marker + line.replace("72 m", "10 m"), 1))
    # The wording the sim really renders (observation["last_action_fact"]).
    real = copy.deepcopy(seen10)
    real["last_action_fact"] = {
        "action": "speak_to", "target": "Maren",
        "note": "Maren is 10 m away — too far to talk to (you do that from within 3 m); "
                "nothing was said"}
    out["Maren 10 m / real sim wording"] = build_prompt("dufus", real, memories)
    return out


EXPERIMENTS = {"phantom_maren": exp_phantom_maren, "survey_trim": exp_survey_trim,
               "close_maren": exp_close_maren, "talk_split": exp_talk_split,
               "roster_removal": exp_roster_removal, "no_coordinates": exp_no_coordinates,
               "context_stress": exp_context_stress, "too_far_fact": exp_too_far_fact}


# ── Sampling ──────────────────────────────────────────────────────────────────

def _one_call(router, model, system, user) -> dict:
    t0 = time.monotonic()
    try:
        raw = router._decide_openrouter(model, system, user)
        decision = llm_router._load_decision_json(raw)
        action = decision.get("action") or {}
        return {"ok": True, "type": action.get("type"),
                "target": action.get("target") or action.get("target_location")
                or action.get("direction"), "message": action.get("message"),
                "thought": decision.get("thought_summary"), "ms": (time.monotonic() - t0) * 1000}
    except Exception as e:      # noqa: BLE001 — a failed sample is data, not a crash
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200],
                "ms": (time.monotonic() - t0) * 1000}


def sample(system: str, user: str, n: int) -> list[dict]:
    router = llm_router.LLMRouter()
    provider = router._resolve_provider(Agent.load(WORLD / "agents", "dufus"))
    if provider != "openrouter":
        sys.exit(f"prompt lab only drives OpenRouter (LLM_PROVIDER={provider})")
    model = router._resolve_model(Agent.load(WORLD / "agents", "dufus"), provider)
    with concurrent.futures.ThreadPoolExecutor(PARALLEL) as pool:
        return list(pool.map(lambda _: _one_call(router, model, system, user), range(n)))


def summarize(samples: list[dict]) -> str:
    counts = collections.Counter(
        f'{s["type"]}' + (f' -> {s["target"]}' if s.get("target") else "")
        if s["ok"] else "ERROR" for s in samples)
    return ", ".join(f"{k}: {v}" for k, v in counts.most_common())


def run(name: str, variants: dict, n: int) -> None:
    RESULTS.mkdir(exist_ok=True)
    out = {"experiment": name, "doc": EXPERIMENTS[name].__doc__ if name in EXPERIMENTS else None,
           "n": n, "variants": {}}
    for label, (system, user) in variants.items():
        samples = sample(system, user, n)
        tokens = (len(system) + len(user)) // 4
        print(f"{label}  (~{tokens} tokens)\n  {summarize(samples)}")
        out["variants"][label] = {"approx_tokens": tokens, "summary": summarize(samples),
                                  "samples": samples}
    path = RESULTS / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["list", "run", "show", "replay"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--only", help="run only variants whose label contains this text")
    args = ap.parse_args()
    if args.command == "list":
        for name, fn in EXPERIMENTS.items():
            print(f"{name}: {' '.join((fn.__doc__ or '').split())}")
    elif args.command == "show":
        for label, (system, user) in EXPERIMENTS[args.target]().items():
            print(f"===== {label} — SYSTEM =====\n{system}\n===== {label} — USER =====\n{user}\n")
    elif args.command == "run":
        variants = EXPERIMENTS[args.target]()
        if args.only:
            variants = {k: v for k, v in variants.items() if args.only in k}
        run(args.target, variants, args.n)
    else:
        data = json.loads(Path(args.target).read_text(encoding="utf-8"))
        run(Path(args.target).stem, {"replayed prompt": (data["system"], data["user"])}, args.n)


if __name__ == "__main__":
    main()
