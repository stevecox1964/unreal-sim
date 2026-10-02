"""Offline tests for the 3 m talk / use rule (#113, revised after SR66_P).

speak_to / inspect_object happen within reach (3.5 m), facing the target.
Farther away nothing happens and the body reports how far — it never walks
off to talk (user: "The APCs should not walk the earth to talk to anyone").
No Unreal: the bridge is a recording stub. Run:
    .venv\\Scripts\\python.exe scripts\\agent_runtime\\test_talk_reach.py
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # Python/
sys.path.insert(0, str(ROOT))

from agent_runtime import llm_router                 # noqa: E402
from agent_runtime.agent_manager import AgentManager  # noqa: E402


def check(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"ok: {label}")


class StubBridge:
    def __init__(self, positions):
        self.positions = positions          # actor name -> (x, y)
        self.calls = []                     # (command, payload)

    def get_character_transform(self, actor_name):
        self.calls.append(("get_character_location", actor_name))
        if actor_name not in self.positions:
            return {"location": None, "rotation": None}
        x, y = self.positions[actor_name]
        return {"location": {"x": x, "y": y, "z": 90.0}, "rotation": None}

    def set_facing(self, actor_name, location, yaw):
        self.calls.append(("set_facing", (actor_name, yaw)))
        return {"status": "success"}

    def execute_action(self, actor_name, action):
        self.calls.append(("execute", (actor_name, dict(action))))
        return {"status": "success"}


class StubAgent:
    def __init__(self, agent_id, name, actor):
        self.agent_id = agent_id
        self.display_name = name
        self.bound_unreal_actor_name = actor
        self.bound_unreal_actor_label = actor
        self.has_unreal_binding = True
        self.active_interrupt = None


def _manager(tmp, maren_xy):
    bridge = StubBridge({"APC_Maren_BP_C_1": maren_xy})
    mgr = AgentManager(worlds_dir=Path(tmp), llm_router=None,
                       unreal_bridge=bridge, memory_store=None)
    mgr._agents_dir = Path(tmp) / "agents"
    mgr.agents = {"dufus": StubAgent("dufus", "Dufus", "APC_Dufus_BP_C_1"),
                  "maren": StubAgent("maren", "Maren", "APC_Maren_BP_C_1")}
    return mgr, bridge


def _say(mgr, to="Maren", kind="speak_to"):
    action = {"type": kind, "target": to, "message": "Morning!"}
    obs = {"location": {"x": 0.0, "y": 0.0, "z": 90.0}, "schedule": {}}
    return mgr._execute_world_action(mgr.agents["dufus"], action, obs)


def _executed(bridge):
    return [p[1] for c, p in bridge.calls if c == "execute"]


def test_in_reach_faces_then_speaks():
    with tempfile.TemporaryDirectory() as tmp:
        mgr, bridge = _manager(tmp, (300.0, 0.0))          # 3 m east
        result = _say(mgr)
        order = [c for c, _ in bridge.calls if c in ("set_facing", "execute")]
        check("in reach: faced first, then said it", order == ["set_facing", "execute"])
        yaw = next(p[1] for c, p in bridge.calls if c == "set_facing")
        check("faced east toward Maren (yaw 0)", abs(yaw) < 1e-6)
        check("the line went to the engine", _executed(bridge)[0]["type"] == "speak_to")
        check("result is the engine's success", result.get("status") == "success")


def test_facing_points_at_the_target():
    with tempfile.TemporaryDirectory() as tmp:
        mgr, bridge = _manager(tmp, (0.0, 250.0))          # 2.5 m south (+Y)
        _say(mgr)
        yaw = next(p[1] for c, p in bridge.calls if c == "set_facing")
        check("faced +Y (yaw 90) toward Maren", abs(yaw - 90.0) < 1e-6)


def test_out_of_reach_does_nothing_and_says_how_far():
    with tempfile.TemporaryDirectory() as tmp:
        mgr, bridge = _manager(tmp, (7200.0, 0.0))         # 72 m east (SR66_P)
        result = _say(mgr)
        check("nothing is executed — no walk, no speech", _executed(bridge) == [])
        check("no turning toward someone 72 m away",
              not any(c == "set_facing" for c, _ in bridge.calls))
        note = result.get("note", "")
        check("the fact says how far, in metres", "72 m away" in note)
        check("the fact uses the display name, never the engine name",
              "Maren" in note and "APC_" not in note)
        check("the result is idle, not a speech success",
              result.get("action") == "idle" and result.get("status") != "success")


def test_reach_edge():
    for dist, inside in ((349.0, True), (351.0, False)):
        with tempfile.TemporaryDirectory() as tmp:
            mgr, bridge = _manager(tmp, (dist, 0.0))
            _say(mgr)
            spoke = any(a["type"] == "speak_to" for a in _executed(bridge))
            check(f"{dist:.0f} cm -> {'speaks' if inside else 'silent'}", spoke is inside)


def test_inspect_object_same_rule():
    with tempfile.TemporaryDirectory() as tmp:
        mgr, bridge = _manager(tmp, (900.0, 0.0))
        result = _say(mgr, kind="inspect_object")
        check("inspect_object at 9 m does nothing", _executed(bridge) == [])
        check("and says it is too far to look closely",
              "too far to look closely at" in result.get("note", ""))


def test_mannequin_passes_through_without_engine_lookup():
    with tempfile.TemporaryDirectory() as tmp:
        mgr, bridge = _manager(tmp, (7200.0, 0.0))
        _say(mgr, to="unknown person")
        check("no engine position lookup for a non-APC name (no false ERROR)",
              not any(c == "get_character_location" for c, _ in bridge.calls))
        check("the line is still said where the APC stands",
              _executed(bridge)[0]["type"] == "speak_to")


def test_nearby_line_marks_close_enough_to_talk():
    lines = llm_router._nearby_character_lines([
        {"name": "Maren", "distance_cm": 280.0},
        {"name": "Hank", "distance_cm": 1200.0},
    ])
    check("within reach: 'close enough to talk'",
          "Maren — about 3 m away — close enough to talk" in lines)
    check("beyond reach: plain distance", "Hank — about 12 m away" in lines
          and "Hank — about 12 m away — close" not in lines)


def test_speak_to_schema_forbids_going_looking():
    text = llm_router._ACTION_SCHEMAS["speak_to"]
    check("speak_to text says nothing is said when too far", "nothing is said" in text)
    check("speak_to text says do not go looking", "Do not go looking" in text)
    check("speak_to text no longer promises a walk-up", "walks up" not in text)


def test_came_close_event():
    """The lizard brain's "someone came close" fires once per arrival in reach."""
    with tempfile.TemporaryDirectory() as tmp:
        mgr, _ = _manager(tmp, (0.0, 0.0))
        here = (0.0, 0.0, 90.0)
        mgr._live_pos = {"dufus": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                         "maren": {"x": 2000.0, "y": 0.0, "yaw": 0.0}}
        near = mgr._nearby_agent_ids("dufus", here)
        close = mgr._nearby_agent_ids("dufus", here, 350.0)
        check("20 m: nearby but not close", near == {"maren"} and close == frozenset())
        mgr._live_pos["maren"]["x"] = 300.0
        check("3 m: close", mgr._nearby_agent_ids("dufus", here, 350.0) == {"maren"})
        check("the reach radius is 3.5 m",
              math.isclose(__import__("agent_runtime.agent_manager",
                                      fromlist=["_REACH_CM"])._REACH_CM, 350.0))


def main():
    test_in_reach_faces_then_speaks()
    test_facing_points_at_the_target()
    test_out_of_reach_does_nothing_and_says_how_far()
    test_reach_edge()
    test_inspect_object_same_rule()
    test_mannequin_passes_through_without_engine_lookup()
    test_nearby_line_marks_close_enough_to_talk()
    test_speak_to_schema_forbids_going_looking()
    test_came_close_event()
    print("\nAll talk-reach checks passed.")


if __name__ == "__main__":
    main()
