# Handoff — both APCs enter Don's and the bank every run; a detour walks round things the navmesh does not know

**Date:** 2026-11-15 11:15
**Branch:** main
**Prior handoff:** [HANDOFF_2026-11-12_1120.md](HANDOFF_2026-11-12_1120.md)

## TL;DR

Six live runs (SR99_P–SR104_P). Dufus and Maren get into Don's Donuts and the American Bank every
run. Maren does bank → Don's → Pawn Shop. A new detour (#126) lets the body look round an object
the navmesh does not know (mannequins, a counter) and walk round it with no model call. Dufus never
finishes Don's because the clerk is a mannequin (#128). The user deleted the bank-corner mannequins
after SR104_P. The next step is to build #128 so Dufus can end his Don's task and walk on.

## What was done this session

- **Prompt audit** of the Claude Code config (report only, no edits applied).
- **Agendas** (`Python/worlds/MCP_World/agents/dufus|maren/agenda.json`): each task block is now 2 h
  wide, and a Pawn Shop task is added for both. Early handover (#125) moves an APC to its next task
  at once, so a 3-minute run covers the morning. Sim clock unchanged.
- **`places.json`** (local, git-excluded): authored spots for Don's Donuts (-3500, -2400) and the
  Pawn Shop (300, -2300) (owner `dufus`, the same stopgap as the bank, #124), plus a "what you can do
  here" list for the Pawn Shop. Spots measured with the engine radar from a distance (roof, ground,
  full path).
- **#126 detour** (`Python/agent_runtime/detour.py`, new; `AgentManager._start_detour`,
  `_end_detour`, `_pulse_detour`): when the last order moved the body nowhere, the body probes the
  radar ring at points round it and picks two hops (out on the open side, then 4 m past toward the
  goal), walks them in the walk phase with no model call, then walks on to the place. Log lines
  start with `DETOUR`.
- **`_execute_world_action`**: a direction step is no longer replaced by the scheduled walk when the
  body does not fit ahead or its last order moved it nowhere.
- **`_apply_cell_verdict`**: refusing the same patch twice gives the model the fact "this changes
  nothing and does not move you" (SR103_P refuse loop).
- **World DB**: deleted the no-go patches the stuck loops wrote today (bank corner, one in Don's).
- **Backlog**: #126 (built), #127 turn first, #128 mannequin clerk, #129 day done → home and sleep,
  #130 sense obstacles early; #125 score table filled for SR99_P–SR104_P.

## In flight

- Not proven: whether the detour start is fast enough without the corner mannequins (#130). The
  pole and other mannequins (Don's counter, Don's door `pose_standing_25/26`) are still there.
- Not tested offline: tests are off (user rule).

## Decisions locked in this session

- **The navmesh is not the whole world** (user). Mannequins and people are not on it, so the body
  must look and plan its own way round. The engine only walks short hops.
- **Mannequins are not filtered in code** (#109). Dufus must learn from "no reply" and move on.
- **Agenda blocks stay 2 h with early handover** for debug runs; the clock is not changed.

## Open questions

- #128: does a line spoken to a figure that never answers count as `spoke` for the task? My proposal:
  yes — the task needs a spoken line, not an answer.
- #130: start the detour on the first `fits=False` contact during travel, or plan the way round
  before contact from a forward sweep? Both are possible; the second needs #127 (turn first).
- The `"owner": "dufus"` stopgap now covers the bank, Don's and the Pawn Shop (#124).

## Next concrete step

Build #128: in `Python/agent_runtime/agent_manager.py`, when a `speak_to` reaches a figure in reach
and no reply comes, record "spoke, no reply" as a body fact and let it satisfy `spoke` for the active
task. Then one live run: pass = Dufus finishes `morning_donut` and walks on to the bank.

## Files touched this session

- `Python/agent_runtime/detour.py` (new) — the two-hop planner over radar probes.
- `Python/agent_runtime/agent_manager.py` — detour start/pulse/end, step-away when blocked, repeat
  refusal fact, constants `_DETOUR_*`.
- `Python/worlds/MCP_World/agents/dufus/agenda.json`, `.../maren/agenda.json` — 2 h blocks, Pawn Shop.
- `Python/worlds/MCP_World/places.json` (local only) — Don's and Pawn Shop spots, Pawn Shop list.
- `Python/worlds/MCP_World/world_places.db` (local) — today's no-go patches deleted.
- `plan/backlog.md` — #126–#130, #125 score table.

## How to resume

Paste this prompt at the start of the next session:

> Resume the previous session. Read `plan/handoffs/LATEST.md` for full context. The next concrete
> step is: build #128 so a line spoken to a figure that never answers counts as `spoke`, then one live
> Play run where Dufus finishes Don's and walks on to the bank. Tests are off until I say so.

How to run live: Unreal in **PIE**. Then `cd Python; uv run python sim_runner.py --port 8777`, and
`curl -X POST http://127.0.0.1:8777/start -H "Content-Type: application/json" -d '{"tick_seconds":1,"mode":"play"}'`;
stop with `curl -X POST http://127.0.0.1:8777/stop`. Restart the runner after every code change.

## Git state at handoff

```
 M MCPGameProject/Config/DefaultEditor.ini      (the user's change; not committed)
```

Recent commits:

```
(this handoff commit)
(the feat commit for #126)
211031b handoff: 2026-11-12 — Places page and the no-subgoal agenda model; the bank is not entered yet, next is one live run
```
