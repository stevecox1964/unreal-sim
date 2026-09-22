"""Goal travel uses remembered places, including places in unsurveyed ground."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent_runtime.agent_manager import AgentManager
from agent_runtime.place_db import PlaceDB
from agent_runtime.world_grid import WorldGrid
from agent_runtime.llm_router import _schedule_note
from agent_runtime import agenda


class Bridge:
    def __init__(self):
        self.calls = []
        self.result = {"status": "success", "moved": True, "path": "full"}

    def execute_action(self, actor, action):
        self.calls.append(action)
        return dict(self.result)


class Agent:
    agent_id = "dufus"
    bound_unreal_actor_name = "APC_Dufus"


class PlaceTravelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge = Bridge()
        self.mgr = AgentManager(worlds_dir=Path(self.tmp.name), llm_router=None,
                                unreal_bridge=self.bridge, memory_store=None)
        self.mgr.world_grid = WorldGrid(cell_size=3000, bounds={
            "min_x": 0, "min_y": 0, "max_x": 14999, "max_y": 14999})
        self.mgr.place_db = PlaceDB(Path(self.tmp.name) / "places.db")
        self.mgr._agents_dir = Path(self.tmp.name) / "agents"

    def obs(self, x, y):
        return {"location": {"x": x, "y": y, "z": 90},
                "grid": self.mgr.world_grid.locate(x, y)}

    def walk(self, name, obs):
        return self.mgr._execute_world_action(Agent(), {
            "type": "walk_to", "target_location": name}, obs)

    def test_learned_shop_beats_district_label(self):
        self.mgr.place_db.set_name("surveyor", 3, 2, "Don's Donuts building", "T0")
        self.mgr.place_db.add_owned_place("maren", 3, 2, "Don's Donuts",
                                          dx=-1000, dy=400, extent_cm=300)
        obs = self.obs(1500, 1500)
        self.walk("Don's Donuts", obs)
        self.assertEqual(self.bridge.calls[-1]["location"], [9500, 7900, 90])
        self.assertEqual(obs["_resolved_target"], [9500, 7900, 90])

    def test_entering_district_does_not_complete_visit(self):
        self.mgr.place_db.set_name("surveyor", 3, 2, "village square", "T0")
        obs = self.obs(9050, 7500)
        self.assertFalse(self.mgr._at_scheduled_place("dufus", {"place": "village square"}, obs))
        self.walk("village square", obs)
        self.assertEqual(self.bridge.calls[-1]["location"], [10500, 7500, 90])

    def test_unsurveyed_place_does_not_require_current_grid(self):
        self.mgr.place_db.add_owned_place("dufus", 3, 2, "home", dx=1200, dy=0,
                                          extent_cm=900)
        obs = {"location": {"x": 1500, "y": 1500, "z": 90}}
        self.walk("home", obs)
        self.assertEqual(self.bridge.calls[-1]["location"], [11700, 7500, 90])
        # This corner of the place extends into another district. Both schedule
        # and execution must agree that it is inside the same square place box.
        arrived = self.obs(12100, 7900)
        self.assertTrue(self.mgr._at_scheduled_place("dufus", {"place": "home"}, arrived))
        self.assertEqual(self.walk("home", arrived)["action"], "idle")

    def test_survey_stand_point_is_the_community_approach(self):
        self.mgr.place_db.set_name("surveyor", 3, 2, "village square", "T0")
        self.mgr.place_db.set_stand_point(3, 2, 10900, 7100)
        self.walk("village square", self.obs(1500, 1500))
        self.assertEqual(self.bridge.calls[-1]["location"], [10900, 7100, 90])

    def test_failed_path_is_not_arrival_and_recovery_can_steer(self):
        self.mgr.place_db.add_owned_place("dufus", 3, 2, "home", dx=0, dy=0, extent_cm=300)
        self.bridge.result = {"status": "success", "path": "none", "moved": False}
        result = self.walk("home", self.obs(1500, 1500))
        self.assertEqual(result["path"], "none")
        self.assertIn("cannot reach", result["note"])
        obs = self.obs(1500, 1500)
        obs["schedule"] = {"status": "travel", "place": "home"}
        self.mgr._attach_route_progress("dufus", obs)
        self.assertEqual(obs["schedule"]["route"]["path_status"], "none")
        self.assertIn("cannot reach", _schedule_note(obs["schedule"]))
        # Local recovery must not be rewritten into the failed named walk.
        self.mgr._plan_move = lambda *args: {"distance_cm": 100, "capped_by": None,
                                            "grew": False}
        self.mgr._execute_world_action(Agent(), {"type": "walk_to", "direction": "east"}, obs)
        self.assertEqual(self.bridge.calls[-1]["location"], [1600, 1500, 90])

    def test_place_moved_during_trip_refreshes_target(self):
        self.mgr.place_db.add_owned_place("dufus", 3, 2, "home", dx=0, dy=0, extent_cm=300)
        self.walk("home", self.obs(1500, 1500))
        self.mgr.place_db.add_owned_place("dufus", 3, 2, "home", dx=1000, dy=0, extent_cm=300)
        self.walk("home", self.obs(1500, 1500))
        self.assertEqual(self.bridge.calls[-1]["location"], [11500, 7500, 90])

    def test_partial_path_keeps_goal_and_exposes_recovery(self):
        self.mgr.place_db.add_owned_place("dufus", 3, 2, "home", dx=0, dy=0, extent_cm=300)
        self.bridge.result = {"status": "success", "path": "partial", "moved": True,
                              "path_end_gap_cm": 1700}
        result = self.walk("home", self.obs(1500, 1500))
        self.assertEqual(result["path_end_gap_cm"], 1700)
        self.assertIn("not yet reached", result["note"])
        obs = self.obs(2000, 1500)
        obs["schedule"] = {"status": "travel", "place": "home"}
        self.mgr._attach_route_progress("dufus", obs)
        text = agenda.prompt_text({"right_now": {"task_id": "visit", "status": "active",
            "place": "home", "route": obs["schedule"]["route"]}})
        self.assertIn("Approaching home", text)
        self.assertIn("inspect another way in", text)
        self.assertNotIn("toward cell", text)

    def test_map_reports_place_distance_within_one_district(self):
        self.mgr.place_db.add_owned_place("dufus", 3, 2, "home", dx=1200, dy=0, extent_cm=300)
        route = self.mgr.route_map_for("dufus", "home", self.obs(9050, 7500))
        self.assertEqual(route["to"]["distance_m"], 26.5)
        self.assertEqual(route["to"]["name"], "home")
        self.assertNotIn("path", route)


if __name__ == "__main__":
    unittest.main()
