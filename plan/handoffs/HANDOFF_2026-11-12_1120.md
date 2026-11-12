# Handoff — a Places page; agenda = where and why, place = what you can do; the bank is not entered yet

**Date:** 2026-11-12 11:20
**Branch:** main — committed locally, **not pushed** (the user ran out of credits)
**Prior handoff:** [HANDOFF_2026-11-11_1050.md](HANDOFF_2026-11-11_1050.md)

## TL;DR

Two things were built. (1) A `/places` page in the web app that edits `places.json`. (2) The
"no subgoals" model: an agenda task says where and why, the place's list says what an APC can do
there. Four live runs (SR95_P–SR98_P). Dufus does Don's Donuts in 2 minutes, and Dufus and Maren
met at the truck and traded vegetables talk. **Nobody has done the bank task for real yet.** The
user deleted the mannequin that blocked the bank door; the run after that (SR98_P) was stopped at
38 s, so the fix is not seen. Evidence and the score table: `plan/backlog.md` #125.

## What was done this session

- **Places page (#124 holds the rough points).** `Python/web_ui/templates/places.html` (new),
  routes `places_page` and `POST /api/places/todo` in `Python/web_ui/main.py`, nav link in
  `base.html`. One editor: choose a place or click a dot → name, owner, X, Y, size, and the
  "what an APC can do here" list. Purple = `places.json` says something about it; grey = a name
  from the world DB (hidden behind a checkbox). For an APC-made place only the list is written.
- **Browser tests** (asked for once, then testing was turned off again):
  `Python/scripts/agent_runtime/test_places_page.py`, dev dependency `playwright`
  (`pyproject.toml`, `uv.lock`). 48 checks passed before the live work started.
- **#125 model (user: "maybe the subgoal is irrelevant").**
  - `llm_router`: a task with no `"inside"` in `needs` reads the place list as soon as the body is
    at the place ("WHAT YOU CAN DO AT …"). New `spot_m` line for an authored place.
  - `agent_manager`: list lookup by `_place_key`; `_owned_place_endpoint` carries `source`; an
    authored place learns and uses no door, and a task that needs `inside` walks on to the
    authored spot (`_AUTHORED_SPOT_CM`); a roof flip over more than `_SAME_DOOR_CM` is not saved
    as a door; a task started early gets its block start clamped to now.
  - `agenda.advance`: a task the APC finished early hands over to the next task at once
    (`prior_task_completed_early`).
  - Agendas rewritten (short "why" sentences): Dufus Don's → American Bank → truck (buy);
    Maren American Bank → Don's → truck (sell).
  - `places.json` (local, git-excluded): lists for "American Bank" and "the vegetable truck";
    place "American Bank" at (-2350, -2600), `"owner": "dufus"` (stopgap, see Open questions).
- **World DB edits by hand:** deleted `place_doors` rows for "vegetable truck" (58.8 m "exit")
  and "american bank" (porch door).

## In flight

- The bank task. Next run decides whether the mannequin was the only blocker.
- Not seen live yet: early handover, the door-gap guard, the `spot_m` walk-on (Maren had the
  `spot_m` line in her prompt in SR97_P and did not follow it).

## Decisions locked in this session

- **Two levels, no subgoals** (user). Agenda task = place + why. Place list = what you can do
  there. A task ends by the clock or by body facts (`needs`); list lines are not tracked.
- **APC-made names are hidden on the Places page, not deleted** (user chose "hide").
- **Testing is off again** (user, 2026-11-12: "turn all testing off"). Memory updated.
- **The user removed the mannequin `pose_standing_5` from the bank door** in the level.

## Open questions

- **`"owner": "dufus"` on the bank is a stopgap.** A community place (and a community landmark)
  only names a 30 m cell; it has no exact spot. Authored places should be exact for everyone (#124).
- **Roof fact vs eyes at a door.** 1.1 m inside the bank door the roof read 2 of 3 (not inside)
  while the picture showed the lobby; the brain believed its eyes and claimed "done".
- **Tiles still grow name-blind** (#113): the bank's tiles reach the pavement; the old runtime
  row "American Bank building interior" covers Don's counter.
- **`command_character_say` for Maren timed out 5 times** in SR95_P; never for Dufus.
- **Qwen 429s are not retried**; blind, Maren did not know her own truck (SR95_P).
- If the walk still stops short at the bank: spot (-1850, -2350) measured free (roof 5/5, full
  path, 8 of 8 headings).
- The Places page is first-pass; the user wants it cleaned up (#124).

## Next concrete step

Unreal in PIE, then one live Play run (commands below). Pass = `scorecard.jsonl` shows
`get_money` in Dufus's `tasks_completed` and `get_change` in Maren's, each with the log line
`body reads INSIDE` near (-2350, -2600), and the log shows `prior_task_completed_early`.
Write the result in the #125 score table.

## Files touched this session

- `Python/web_ui/main.py`, `Python/web_ui/templates/base.html`, `Python/web_ui/templates/places.html` (new)
- `Python/scripts/agent_runtime/test_places_page.py` (new), `Python/pyproject.toml`, `Python/uv.lock`
- `Python/agent_runtime/agenda.py`, `agent_manager.py`, `llm_router.py`
- `Python/worlds/MCP_World/agents/dufus/agenda.json`, `agents/maren/agenda.json`
- `Python/worlds/MCP_World/places.json` (local only), `world_places.db` (two door rows deleted)
- `plan/backlog.md` (#124, #125)

## How to resume

Paste this prompt at the start of the next session:

> Resume the previous session. Read `plan/handoffs/LATEST.md` for full context. The work of 2026-11-12 is committed locally and not pushed. The next concrete step is one live Play run to see if Maren and Dufus now enter the American Bank (I deleted the mannequin in the doorway), then fill the #125 score table in `plan/backlog.md`. Tests are off until I say so.

How to run live: Unreal in **PIE**. Then `cd Python; uv run python sim_runner.py --port 8777`, and
`curl -X POST http://127.0.0.1:8777/start -H "Content-Type: application/json" -d '{"tick_seconds":1,"mode":"play"}'`;
stop with `curl -X POST http://127.0.0.1:8777/stop`. Restart the runner after every code change.
The Places page: `Python\start_sim.bat`, then `http://127.0.0.1:8765/places`.

## Git state at handoff

```
 M MCPGameProject/Config/DefaultEditor.ini      (the user's change; not committed)
```

Not pushed. Recent commits:

```
(this handoff commit)
bcf797c feat: Places page; agenda says where and why, the place says what you can do (#124, #125); SR95-98_P findings
8594d1d handoff: 2026-11-11 — Dufus walks in by a remembered door, walks up to the clerk, turns and orders; next is Maren at Don's
```
