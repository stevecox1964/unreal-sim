"""Walk round a thing the engine path did not know (SR100_P / SR101_P).

A named walk is handed to the engine, and the engine walks a navmesh path. The
navmesh does not know everything that stands in the world: mannequins, other
bodies, a parked car. SR100_P: Maren's walk from Don's to the Pawn Shop ran
into two mannequins on the bank corner, the path still read "full", and every
new order was the same path into the same two mannequins.

So the body looks before it walks on. It feels the ground round the thing with
its own capsule (the radar ring, measured at a point) and picks two short
hops: out of contact on whatever side is open, then past the thing toward the
goal. The engine is only asked to walk each short hop; it is not asked for the
way round.

Pure functions. The caller owns the engine: ``probe(x, y)`` returns how far the
body can travel from that point on eight headings, relative to the heading of
travel — ``{0: cm, 45: cm, 90: cm, 135: cm, 180: cm, -135: cm, -90: cm,
-45: cm}`` (+90 is the right hand) — or ``None`` when the point has no ground
or could not be measured. ``None`` is never "clear".
"""
from __future__ import annotations

import math

# Which way the first hop may go, relative to the goal heading, in the order
# tried: sideways first (it gets round the thing soonest), then back on a
# slant, then forward on a slant, then straight back. SR102_P: from Maren's
# spot straight back had 0.9 m of room and back-right had 7 m.
OUT_REL = (90, -90, 135, -135, 45, -45, 180)
# How far the first hop goes. The first that leads to a clear way past wins.
OUT_CM = (120.0, 220.0, 350.0)
# Which way the second hop may go: toward the goal, or on a slant toward it.
PAST_REL = (0, 45, -45)
# How far the second hop goes past the point of the first.
PASS_CM = 400.0
# Free travel a hop must have beyond its own length, so a hop never ends in
# contact with the next thing.
MARGIN_CM = 40.0
# A point where the body cannot travel this far on any heading is inside
# something; no hop may end there.
ROOM_CM = 100.0
# Each probe is one engine round trip; stop looking after this many.
MAX_PROBES = 24


def _step(x: float, y: float, yaw_deg: float, cm: float) -> tuple[float, float]:
    r = math.radians(yaw_deg)
    return x + math.cos(r) * cm, y + math.sin(r) * cm


def plan(here: tuple[float, float], heading_deg: float, probe) -> dict | None:
    """Return the hops round the thing ahead, or ``None`` when none measured clear.

    ``{"hops": [(x, y), (x, y)], "out_rel", "out_cm", "past_rel",
    "side": "left"|"right"|"back", "probes": n}``. Every hop was measured:
    ground under it, and free travel along the line to it.
    """
    probes = 0
    ring_here = probe(here[0], here[1])
    probes += 1
    if ring_here is None:
        return None

    for out_rel in OUT_REL:
        for out_cm in OUT_CM:
            if ring_here.get(out_rel, 0.0) < out_cm + MARGIN_CM:
                break
            if probes >= MAX_PROBES:
                return None
            p1 = _step(here[0], here[1], heading_deg + out_rel, out_cm)
            ring1 = probe(p1[0], p1[1])
            probes += 1
            if ring1 is None or max(ring1.values(), default=0.0) < ROOM_CM:
                continue
            for past_rel in PAST_REL:
                if ring1.get(past_rel, 0.0) < PASS_CM + MARGIN_CM:
                    continue
                if probes >= MAX_PROBES:
                    return None
                p2 = _step(p1[0], p1[1], heading_deg + past_rel, PASS_CM)
                ring2 = probe(p2[0], p2[1])
                probes += 1
                if ring2 is None or max(ring2.values(), default=0.0) < ROOM_CM:
                    continue
                side = ("back" if out_rel == 180 else
                        "right" if out_rel > 0 else "left")
                return {"hops": [p1, p2], "out_rel": out_rel, "out_cm": out_cm,
                        "past_rel": past_rel, "side": side, "probes": probes}
    return None
