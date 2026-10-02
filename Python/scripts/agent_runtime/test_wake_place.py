"""Offline tests for the wake/already-there place fix (user, 2026-07-05).

No Unreal, no network. Run:
    .venv\\Scripts\\python.exe scripts\\agent_runtime\\test_wake_place.py

The bug: the sequencer's "am I already there?" was a name-only match against
the community cell name, so on a fresh world (nothing named yet) an agent
standing at its scheduled place was told to travel — Maren woke at her stall
and wandered off hunting for "the vegetable truck".

Covers:
  - planner.step(at_place=...): geometric ground truth overrides the name
    match in both directions; None falls back to the legacy name match.
  - AgentManager._at_scheduled_place: community cell = same grid cell;
    owned place = standing on one of its 3 m tiles (#113); unresolvable = None.
  - Place growth (#113): touching tiles join, far/stuck/full do not; one tile
    set per place name across owners.
  - Wake seeding: the agent's FIRST schedule step of a run seeds an unknown
    scheduled place as the agent's own place cell centered where it stands
    (first-time place-cell initialization); later steps never seed.
  - End-to-end _attach_schedule: Maren wakes at her (unnamed) stall ->
    status "act", owned place created; a later unknown place -> "travel".
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # Python/
sys.path.insert(0, str(ROOT))

from agent_runtime import planner                        # noqa: E402
from agent_runtime.agent_manager import AgentManager     # noqa: E402
from agent_runtime.place_db import PLACE_EXTENT_CM, PlaceDB  # noqa: E402
from agent_runtime.world_grid import TILE_CM, WorldGrid  # noqa: E402


def check(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"ok: {label}")


SCHED = [{"start": "08:00", "end": "12:00",
          "activity": "tend the stall", "place": "the vegetable truck"}]


def test_planner_at_place_override():
    nine = 9 * 60
    d = planner.step(SCHED, nine, current_place=None, at_place=True)
    check("at_place=True -> act (position beats missing name)", d["status"] == "act")
    d = planner.step(SCHED, nine, current_place="the vegetable truck", at_place=False)
    check("at_place=False -> travel (position beats matching name)", d["status"] == "travel")
    d = planner.step(SCHED, nine, current_place="the vegetable truck", at_place=None)
    check("at_place=None -> legacy name match still acts", d["status"] == "act")
    d = planner.step(SCHED, nine, current_place=None, at_place=None)
    check("at_place=None + unknown place -> legacy travel", d["status"] == "travel")


class StubBridge:
    def execute_action(self, actor_name, action):
        return {"status": "accepted", "action": action.get("type")}


def _manager(tmp):
    mgr = AgentManager(worlds_dir=Path(tmp), llm_router=None,
                       unreal_bridge=StubBridge(), memory_store=None)
    mgr._agents_dir = Path(tmp) / "agents"
    # cell (5,5) covers x,y in [0,400): grid index (0,0), center (200,200).
    mgr.world_grid = WorldGrid(cell_size=400.0,
                               bounds={"min_x": -2000, "min_y": -2000,
                                       "max_x": 1999, "max_y": 1999})
    mgr.place_db = PlaceDB(Path(tmp) / "world_places.db")
    mgr.agents = {}
    return mgr


def _obs(mgr, x, y, world_time="Day 1, 09:00"):
    return {"location": {"x": x, "y": y, "z": 90.0},
            "grid": mgr.world_grid.locate(x, y),
            "place": [], "place_context": {}, "world_time": world_time}


BLOCK = SCHED[0]


def test_at_scheduled_place_geometry():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _manager(tmp)

        # Unresolvable, no seeding allowed -> unknown.
        check("unknown place -> None",
              mgr._at_scheduled_place("maren", BLOCK, _obs(mgr, 320.0, 120.0)) is None)
        check("no block -> None", mgr._at_scheduled_place("maren", None, _obs(mgr, 0, 0)) is None)
        check("nothing was seeded", mgr.place_db.all_owned_places() == [])

        # Community-named cell: "there" = standing in that grid cell.
        mgr.place_db.set_name("dufus", 5, 5, "the vegetable truck", "T0")
        check("in the community cell -> True",
              mgr._at_scheduled_place("maren", BLOCK, _obs(mgr, 320.0, 120.0)) is True)
        check("outside the community cell -> False",
              mgr._at_scheduled_place("maren", BLOCK, _obs(mgr, 1500.0, 1500.0)) is False)


def _tile_center(mgr, tx, ty):
    g = mgr.world_grid
    return g.origin_x + (tx + 0.5) * TILE_CM, g.origin_y + (ty + 0.5) * TILE_CM


def _tiles(mgr, name):
    return {(t["tx"], t["ty"]): t for t in mgr.place_db.place_tiles(name)}


def test_at_scheduled_place_owned_tiles():
    """#113: arrival = standing on one of the place's 3 m tiles. The first
    resolve seeds every tile the old 9 m box touches, so no spot that used to
    count as arrival stops counting."""
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _manager(tmp)
        # Owned place anchored at cell (5,5) center (200,200) + (120,-80) = (320,120).
        mgr.place_db.add_owned_place("maren", 5, 5, "the vegetable truck",
                                     dx=120.0, dy=-80.0)
        ax, ay = mgr.world_grid.tile_of(320.0, 120.0)
        at = lambda x, y: mgr._at_scheduled_place("maren", BLOCK, _obs(mgr, x, y))
        check("at the anchor point -> True", at(320.0, 120.0) is True)
        half = PLACE_EXTENT_CM / 2.0
        x0, y0 = mgr.world_grid.tile_of(320.0 - half, 120.0 - half)
        x1, y1 = mgr.world_grid.tile_of(320.0 + half, 120.0 + half)
        check("seeded every tile the old 9 m box touches",
              set(_tiles(mgr, "the vegetable truck"))
              == {(i, j) for i in range(x0, x1 + 1) for j in range(y0, y1 + 1)})
        check("old box edge (just inside) still counts", at(320.0 + half - 1, 120.0) is True)
        check("seed tiles are marked seed, not stood",
              all(t["source"] == "seed" for t in _tiles(mgr, "the vegetable truck").values()))
        check("corner seed tile -> True", at(*_tile_center(mgr, x1, y1)) is True)
        check("one tile past the edge -> False", at(*_tile_center(mgr, x1 + 1, ay)) is False)


def test_place_grows_from_the_body():
    """#113: a tile the APC stands on joins its bound place when it touches
    the place (8-neighbour); farther tiles, stuck ticks and a full place do not."""
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _manager(tmp)
        name = "the vegetable truck"
        mgr.place_db.add_owned_place("maren", 5, 5, name, dx=120.0, dy=-80.0)
        ax, ay = mgr.world_grid.tile_of(320.0, 120.0)
        at = lambda x, y: mgr._at_scheduled_place("maren", BLOCK, _obs(mgr, x, y))
        at(320.0, 120.0)   # first resolve lays the seed tiles
        east = max(tx for tx, _ in _tiles(mgr, name))   # the seeded east edge column
        grow = lambda tx, ty, stuck=False: mgr._grow_place(
            "maren", _obs(mgr, *_tile_center(mgr, tx, ty)), name, stuck)

        grow(ax, ay)
        anchor = _tiles(mgr, name)[(ax, ay)]
        check("standing on a seed tile promotes it to stood",
              anchor["source"] == "stood" and anchor["visits"] == 1
              and anchor["first_by"] == "maren")
        grow(ax, ay)
        check("standing there again counts the tick",
              _tiles(mgr, name)[(ax, ay)]["visits"] == 2)

        check("before growth the edge+1 tile is not the place",
              at(*_tile_center(mgr, east + 1, ay)) is False)
        grow(east + 1, ay)
        check("a touching tile is added as stood",
              _tiles(mgr, name).get((east + 1, ay), {}).get("source") == "stood")
        check("arrival counts the grown tile",
              at(*_tile_center(mgr, east + 1, ay)) is True)

        grow(east + 3, ay)
        check("a tile two away is not added", (east + 3, ay) not in _tiles(mgr, name))
        grow(east + 2, ay, stuck=True)
        check("a stuck tick adds nothing", (east + 2, ay) not in _tiles(mgr, name))

        mgr.place_db.add_owned_place("dufus", 5, 5, "The Vegetable Truck",
                                     dx=-150.0, dy=60.0)
        check("another owner's same-name place shares the tile set",
              set(_tiles(mgr, "The Vegetable Truck")) == set(_tiles(mgr, name)))

        # Two different places that share a name ("home": dufus's and maren's,
        # 168 m apart in the real world) must NOT share tiles — arriving at one
        # is not arriving at the other.
        cx, cy = mgr.world_grid.cell_center(0, 0)
        fx, fy = cx - 3000.0, cy - 3000.0                  # ~70 m from maren's place
        mgr.place_db.add_owned_place("dufus", 0, 0, name, dx=-3000.0, dy=-3000.0)
        dufus_at = lambda x, y: mgr._at_scheduled_place("dufus", BLOCK, _obs(mgr, x, y))
        check("standing at the far place counts for its owner", dufus_at(fx, fy) is True)
        check("the far place got its own tile set",
              len({t["place_key"] for t in mgr.place_db.place_tiles(name)}) == 2)
        check("standing at maren's place is not arriving at dufus's far one",
              dufus_at(320.0, 120.0) is False)
        check("and maren still arrives at hers",
              mgr._at_scheduled_place("maren", BLOCK, _obs(mgr, 320.0, 120.0)) is True)

        import agent_runtime.agent_manager as am
        saved = am._PLACE_MAX_TILES
        am._PLACE_MAX_TILES = len([t for t in mgr.place_db.place_tiles(name)
                                   if "@" not in t["place_key"]])   # maren's place only
        try:
            grow(east + 2, ay)
            check("a full place does not grow", (east + 2, ay) not in _tiles(mgr, name))
        finally:
            am._PLACE_MAX_TILES = saved
        grow(east + 2, ay)
        check("below the cap it grows again", (east + 2, ay) in _tiles(mgr, name))


def test_wake_seeds_unknown_place():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _manager(tmp)
        at = mgr._at_scheduled_place("maren", BLOCK, _obs(mgr, 320.0, 120.0),
                                     seed_if_unknown=True)
        check("wake seed -> already there", at is True)
        owned = mgr.place_db.owned_places_in_cell(5, 5)
        check("owned place created", len(owned) == 1
              and owned[0]["name"] == "the vegetable truck"
              and owned[0]["owner"] == "maren")
        check("centered where the agent stands",
              owned[0]["dx"] == 120.0 and owned[0]["dy"] == -80.0)
        check("9x9 m box", owned[0]["extent_cm"] == PLACE_EXTENT_CM == 900.0)


class StubAgent:
    """Duck-typed Agent: just what ensure_daily_plan + step consume."""
    def __init__(self, agent_id, blocks):
        self.agent_id = agent_id
        self.last_activity = None
        self.character_text = "stub"
        self.goals_text = "stub"
        self.daily_schedule_day = "Day 1"
        self.daily_schedule_blocks = blocks

    def set_daily_schedule(self, blocks, day, agents_dir=None):
        self.daily_schedule_blocks, self.daily_schedule_day = blocks, day


def test_attach_schedule_wake_flow():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _manager(tmp)
        maren = StubAgent("maren", [dict(b) for b in SCHED])

        # Wake: standing at the (unrecorded) stall -> act, and the stall is
        # seeded as her own 9x9 m place cell (first-time initialization).
        obs = _obs(mgr, 320.0, 120.0)
        mgr._attach_schedule(maren, obs)
        check("wake at the stall -> act (not travel)",
              obs["schedule"]["status"] == "act")
        check("stall seeded on wake",
              mgr.place_db.find_owned_place("the vegetable truck") is not None)

        # Later step, different unknown place -> travel, and NO seeding.
        maren.daily_schedule_blocks[0]["place"] = "Don's Donuts"
        obs2 = _obs(mgr, 320.0, 120.0)
        mgr._attach_schedule(maren, obs2)
        check("later unknown place -> travel", obs2["schedule"]["status"] == "travel")
        check("later steps never seed",
              mgr.place_db.find_owned_place("Don's Donuts") is None)

        # A new run rearms the wake seed (start_simulation clears the marker).
        mgr._wake_stepped.clear()
        obs3 = _obs(mgr, 320.0, 120.0)
        mgr._attach_schedule(maren, obs3)
        check("next run's first step may seed again",
              mgr.place_db.find_owned_place("Don's Donuts") is not None)
        check("re-armed wake -> act at the new spot", obs3["schedule"]["status"] == "act")


def test_wake_directive_at_spawn():
    # Spool-up (SR2 regression): the directive is computed at the TRUE spawn
    # before the orient LLM can move the agent — it seeds the scheduled place
    # right there and reports "act", and consumes the once-per-run seed chance
    # so later ticks can't stamp the place mid-walk.
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _manager(tmp)
        maren = StubAgent("maren", [dict(b) for b in SCHED])
        loc = {"x": 320.0, "y": 120.0, "z": 90.0}
        grid = mgr.world_grid.locate(320.0, 120.0)

        d = mgr._wake_directive(maren, loc, grid, "Day 1, 09:00")
        check("wake directive says act at the spawn", d and d["status"] == "act")
        check("scheduled place seeded at the spawn",
              mgr.place_db.find_owned_place("the vegetable truck") is not None)
        check("seed chance consumed by the spool-up", "maren" in mgr._wake_stepped)

        # The agent then wanders off; a later tick with a different unknown
        # place must not seed it (the wake already happened).
        maren.daily_schedule_blocks[0]["place"] = "Don's Donuts"
        obs = _obs(mgr, 1500.0, 1500.0)
        mgr._attach_schedule(maren, obs)
        check("post-wake ticks never seed",
              mgr.place_db.find_owned_place("Don's Donuts") is None)
        check("post-wake directive is travel", obs["schedule"]["status"] == "travel")


def test_positionless_tick_keeps_seed_chance():
    # A first tick without position data (no location/grid yet) must not burn
    # the once-per-run seed — the next tick that has a position seeds.
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _manager(tmp)
        maren = StubAgent("maren", [dict(b) for b in SCHED])

        blind = {"place": [], "place_context": {}, "world_time": "Day 1, 09:00"}
        mgr._attach_schedule(maren, blind)
        check("blind tick seeded nothing", mgr.place_db.all_owned_places() == [])
        check("blind tick kept the seed chance", "maren" not in mgr._wake_stepped)

        obs = _obs(mgr, 320.0, 120.0)
        mgr._attach_schedule(maren, obs)
        check("first positioned tick seeds",
              mgr.place_db.find_owned_place("the vegetable truck") is not None)
        check("and reports act", obs["schedule"]["status"] == "act")


def test_wake_sweep_drops_community_breadcrumb():
    # User, 2026-07-06: every explored district should get a community place
    # cell — the wake look-around counts as the cell's sweep. Act ticks are
    # sweep-exempt, so an agent working its own cell (Dufus at home) would
    # otherwise never put its district on the map.
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _manager(tmp)
        views = [{"direction": "forward", "yaw": 0.0,
                  "landmarks": [{"label": "farmhouse", "confidence": 0.9}]},
                 {"direction": "left", "yaw": -90.0, "landmarks": []}]

        mgr._ingest_wake_views("dufus", 5, 5, views, "Day 1, 07:00")
        swept = mgr.place_db.get_swept(5, 5)
        check("wake sweep drops the community breadcrumb",
              swept is not None and swept["swept_by"] == "dufus")
        cells = mgr.place_db.map_cells()
        check("the district shows on the map as swept",
              len(cells) == 1 and cells[0]["state"] == "swept")
        check("landmarks were ingested", cells[0]["landmarks"] == 1)

        # Idempotent: a second wake in the same cell keeps the first sweep.
        mgr._ingest_wake_views("maren", 5, 5, views, "Day 2, 07:00")
        check("first sweep wins", mgr.place_db.get_swept(5, 5)["swept_by"] == "dufus")

        # An empty sweep (no transform / all headings failed) records nothing.
        mgr._ingest_wake_views("dufus", 6, 6, [], "Day 1, 07:00")
        check("empty wake sweep leaves the cell unexplored",
              mgr.place_db.get_swept(6, 6) is None)


def test_wake_schedule_line_rendering():
    from agent_runtime.llm_router import _wake_schedule_line
    act = _wake_schedule_line({"status": "act", "place": "the vegetable truck",
                               "activity": "tend the stall"})
    check("act verdict confirms position", "CONFIRMS" in act and "Do NOT walk" in act)
    travel = _wake_schedule_line({"status": "travel", "place": "Don's Donuts",
                                  "activity": "eat lunch"})
    check("travel verdict says not there yet", "NOT there yet" in travel
          and 'target_location "Don\'s Donuts"' in travel)
    check("no directive -> generic guidance",
          "No schedule verdict" in _wake_schedule_line(None))
    check("idle -> free to choose",
          "Nothing is scheduled" in _wake_schedule_line({"status": "idle"}))


def main():
    test_planner_at_place_override()
    test_at_scheduled_place_geometry()
    test_at_scheduled_place_owned_tiles()
    test_place_grows_from_the_body()
    test_wake_seeds_unknown_place()
    test_attach_schedule_wake_flow()
    test_wake_directive_at_spawn()
    test_positionless_tick_keeps_seed_chance()
    test_wake_sweep_drops_community_breadcrumb()
    test_wake_schedule_line_rendering()
    print("\nAll wake-place checks passed.")


if __name__ == "__main__":
    main()
