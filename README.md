<div align="center">

# AI Agent Simulation
<span style="color: #555555">unreal-sim</span>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Unreal Engine](https://img.shields.io/badge/Unreal%20Engine-5.5%2B-orange)](https://www.unrealengine.com)
[![Python](https://img.shields.io/badge/Python-3.12%2B-yellow)](https://www.python.org)
[![Status](https://img.shields.io/badge/Status-Experimental-red)](https://github.com/chongdashu/unreal-mcp)

**Fork of [chongdashu/unreal-mcp](https://github.com/chongdashu/unreal-mcp)**

</div>

> This is a fork of [chongdashu/unreal-mcp](https://github.com/chongdashu/unreal-mcp). Original work by [@chongdashu](https://www.x.com/chongdashu). This fork extends the base project with additional features â€” see [Changes from Upstream](#changes-from-upstream) below.

This project is an **AI agent simulation** built to interact with Unreal Engine: LLM-driven APCs (AI NPCS) that can perceive the 3D game world through their in-game cameras (soon to be vision model), and decide what to do (via decision LLM), remember what they have seen and who they have met, and navigate to named places running live in PIE or as a standalone process. It began as a fork of an Unreal *MCP* (editor-authoring) project; MCP has been removed and direct calls to python->Unreal C++ are being made.

## Experimental Status

This project is currently in an **EXPERIMENTAL** state. The API, functionality, and implementation details are subject to significant changes. While we encourage testing and feedback, please be aware that:

- Breaking changes may occur without notice
- Features may be incomplete or unstable
- Documentation may be outdated or missing
- Production use is not recommended at this time

## Overview

What the sim does each tick, per agent:

| Stage | What happens |
|-------|--------------|
| **Perceive** | Capture the agent's in-game camera frame; a vision model turns it into landmarks + characters + footing (what the agent is standing on) + a caption. |
| **Remember** | Sightings, places, and interactions are written to per-agent episodic + social memory and a shared spatial map. |
| **Decide** | A decision LLM picks the next action from the agent's allowed action set, grounded in what it sees and remembers, its authored agenda (`agenda.json`), and deterministic facts like footing and route progress. |
| **Sense (body)** | Before any model runs, the body measures: a radar sweep on all 8 compass headings, the ground under the feet, and roof rays overhead ("inside" or "outdoors"). These are facts in the prompt; the engine's names never reach the model. |
| **Act** | The action is schema-validated, then executed in Unreal (walk to a named place, walk at a doorway or a person the eyes listed, speak to someone, observe, idle, ...). The body measures every step and reports what really happened. |

Decisions stream to `worlds/<level>/logs/agent_decisions.log` (completed decisions only) and
`worlds/<level>/logs/sim_runner.log` (every tick's outcome for every agent, including skips and
exclusions truncated per run), plus the web cockpit's live feed.

> **Note (2026-06-28):** the **Python MCP editor-authoring tools were retired** (Actor Management,
> Blueprint Development, Blueprint Node Graph, Editor Control, Camera, Project). Epic now ships an
> official Unreal MCP for editor authoring, so maintaining ours wasn't worth it. The sim is driven by
> a **standalone runner + web cockpit** (no Claude/MCP required). The underlying C++ commands still
> exist in the plugin (reachable over the raw socket on `:55557`).
> The bridge currently lives in an editor-only module, so **Unreal must be running in PIE** to host
> the socket (making it a runtime module for a packaged, editor-free build is on the backlog).
>
> **Update (2026-07-08):** the Python MCP layer is now **fully retired** (backlog #22) no MCP
> server, no `mcp.json`, no `mcp`/`fastmcp` dependency. The sim talks to Unreal over raw TCP via
> `agent_runtime/unreal_connection.py`, and anything driving the sim (web cockpit, Claude in dev
> mode, curl) uses the runner's localhost HTTP API.

## What an APC does at a place (state on 2026-11-11)

Proven live with one APC (Dufus), one shop (Don's Donuts) and one mannequin clerk — runs
SR83_P to SR94_P. Findings and limits: [`plan/backlog.md`](plan/backlog.md) #115, #116, #118–#123.

- **Inside is a body fact (#115).** The radar command sends one ray up at the body and one at each
  reachable spot 2 m around it. A roof over all of them = "inside". The eyes' label is not used.
- **The eyes lead to a door (#115).** The vision model reports `ways_in` (open doorways and where
  they sit across the picture). `walk_to` with direction `way-in-1` walks that line; a long line
  stops 4 m short for a second look. The engine's own door answer is written to the log only, to
  score the eyes.
- **A place remembers its door, exit and things (#118).** When the roof fact flips, the body saves
  the crossing on the place (`place_doors` in `world_places.db`). The next `walk_to "<place>"`
  goes straight to the first point inside. What the eyes name while inside is saved as a thing in
  that place (`place_things`), not as a new place. A body that goes in more than 6 m from the
  remembered door is told it may be in another building.
- **"I have been here before" (#122).** A spot (0.5 m) and facing (5°) the eyes already reported is
  answered from `observations/perception_log.jsonl` with no cloud vision call. Never reused when
  another APC is near.
- **Walk up, turn, then speak (#113, #123).** `speak_to` works only from close up, facing the
  target. For an APC the engine gives the distance. For a figure the engine cannot place (a
  mannequin clerk) the eyes give `person-N` and its place in the picture: `walk_to` direction
  `person-1` walks up to it (the body stops at the counter), and `speak_to` turns the body to face
  it. Each CHARACTER line says "close enough to speak to" or not, before the model decides.
- **A place has a "what you can do here" list (#120, first slice).** Authored in
  `worlds/<level>/places.json` under `"todo"`; shown to an APC only when its body reads inside.
- **A task's "done" needs body facts (#116).** `completion.needs` in `agenda.json` (`inside`,
  `spoke`): the model's `task_completion` is refused while a fact is missing, and it is told which.
- **Run scorecard (#119).** At stop, code appends one line per APC to
  `worlds/<level>/logs/scorecard.jsonl`: seconds and decisions to get inside, steps, eye calls,
  looks reused, failed calls, tasks done, cost.

Measured on the same task ("walk to Don's, order at the counter"): first visit 229–279 s and 9–12
decisions to get inside; with the remembered door 29–37 s and 1 decision; whole task 46 s, 3
decisions, about $0.09 (SR94_P).

## Components

### Sample Project (MCPGameProject) `MCPGameProject`
- Based off the Blank Project, but with the unrealSIM plugin added.

### Plugin (UnrealMCP) `MCPGameProject/Plugins/UnrealMCP`
- Native TCP server for MCP communication
- Integrates with Unreal Editor subsystems
- Implements actor manipulation tools
- Handles command execution and response handling

### Python Runtime `Python/`
- Standalone no Claude/MCP required to run the sim: `Python/start_sim.bat` or `python Python/sim_runner.py`
- `agent_runtime/unreal_connection.py` owns the raw TCP socket to the Unreal bridge plugin (port 55557)
- Handles command serialization, response parsing, and reconnection (Unreal closes the socket after each command)
- Loads `Python/.env` for LLM-backed NPC simulation settings

## Directory Structure

- **MCPGameProject/** Example Unreal project
  - **Plugins/UnrealMCP/** C++ plugin source

- **Python/** the standalone agent runtime (no MCP retired 2026-07-08)
  - **agent_runtime/** the cognitive loop: `agent_manager` (tick orchestration), `factory`
    (shared AgentManager construction), `llm_router`, `perception` (VLM), `memory_store`,
    `social_memory` + `episodic_memory` (per-agent memory), `place_db` + `world_grid` (shared
    spatial map), `cell_sweep` (the place-cell sweep any APC can run), `places_manifest` (`places.json`),
    `run_score` (the run scorecard), `config_store`, `unreal_bridge`
  - **scripts/** offline test suite (`run_tests.py`) + the loop harness (`loop/preflight.py`)
  - **worlds/** Level-scoped NPC data (one folder per Unreal level)
    - **`<LevelName>`/agents/`<agent_id>`/** per-NPC config files
      - `state.json` identity, binding, tier, goal, tick settings
      - `character.md` role, personality, backstory
      - `goals.md`  long-term and current goals
      - `rules.md` decision constraints
      - `tools.json` allowed action list
      - `memory.json` / `social.json` / `episodes.jsonl` â€” accumulated runtime memory (git-ignored)
    - **`<LevelName>`/`world_places.db`** â€” shared spatial map (place cells + landmarks; git-ignored)
    - **`<LevelName>`/logs/** â€” per-world decision logs (runtime, git-ignored)
  - **web_ui/** â€” the web cockpit (FastAPI + Jinja2): the `/sim` controller (start/stop/step + live
    decision feed), the `/providers` page (provider-profile CRUD), and the `/settings` page
  - `sim_runner.py` â€” standalone sim engine (control API on `:8777`)
  - `start_sim.bat` â€” launches the sim engine + web cockpit (NPC scaffolding now lives in the `/create-npc` skill, not a web builder)

- **Docs/** â€” Comprehensive documentation
  - See [Docs/README.md](Docs/README.md) for documentation index

## ðŸš€ Quick Start Guide

### Running the sim (standalone — no Claude/MCP)

This is the primary path. Start things in this order:

1. **Run the Unreal project in PIE** — open the project and press **Play**. This starts the C++ TCP server (`:55557`) the sim talks to. **Run exactly one editor instance**: only one process can own `:55557`, so a second editor leaves the sim driving a window you aren't watching.
2. **Start the sim engine + web cockpit** — run `Python/start_sim.bat` (the repo's one batch file). It launches:
   - the **sim engine** (`sim_runner.py`) on `http://127.0.0.1:8777` — owns the agent loop and the single Unreal socket, exposing a localhost JSON control API (`/status`, `/start`, `/stop`, `/tick`, `/events`).
   - the **web cockpit** on `http://127.0.0.1:8765/sim` — start/stop/step the sim and watch the live decision feed. **The cockpit page opens itself in your browser** once the server is listening.

### Authoring places — Landmarks (setup phase, in the editor)

Ground-truth places are authored by dropping a marker actor in the level and setting its **actor
label** to `Landmark_<owner>_<place name with underscores>`:

```
Landmark_maren_vegetable_truck   -> maren's "vegetable truck"
Landmark_dufus_home              -> dufus's "home"
Landmark_community_town_square   -> shared "town square"
```

Any actor class works (a dedicated `Landmark_BP` marker, or rename a real prop to pin the place to
it). Owner is case-insensitive; the sim scans landmarks at start, and `/map` → **Sync world**
rescans after you move things — the tip line lists exactly which landmarks applied and flags
near-miss labels (`Landmarlk_...`) as spelling suspects. Landmarks win over `places.json` on
collision; moving the actor moves the place.

**What an APC can do at a place** is authored in `Python/worlds/<level>/places.json`, by place
name (no x/y needed), and shown to an APC only when its body is inside that place:

```json
{ "places": [],
  "todo": [ { "place": "Don's Donuts",
              "items": [ "Order a coffee or a donut: walk up to the counter, face the person behind it, and say your order",
                         "Sit at a table and eat" ] } ] }
```

Because the engine is a plain JSON HTTP API, you can also drive it directly with curl:

```bash
curl http://127.0.0.1:8777/status
curl -X POST http://127.0.0.1:8777/start -H "Content-Type: application/json" -d '{"tick_seconds":1,"mode":"play"}'
curl http://127.0.0.1:8777/events?limit=20
curl -X POST http://127.0.0.1:8777/stop
```

### Dev mode (Claude Code operating the sim)

When Claude Code is running it can start/stop the sim and help read logs + debug — it drives the
same runner HTTP API as the cockpit (`http://127.0.0.1:8777`). The MCP path was retired 2026-07-08
(#22). Always start Unreal in PIE first — without it the bridge socket isn't hosted.

For LLM key/model changes, a process restart is not needed: the simulation layer reloads
`Python/.env` before LLM decisions.

### Prerequisites
- Unreal Engine 5.5+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (used by `start_sim.bat` to run the Python side)

> **Python setup:** Uninstall any existing Python versions before proceeding. Then install Python 3.12+ fresh from [python.org](https://www.python.org/downloads/). Multiple Python versions can cause environment conflicts.

### Sample project

For getting started quickly, feel free to use the starter project in `MCPGameProject`. This is a UE 5.5 Blank Starter Project with the `UnrealMCP.uplugin` already configured. 

1. **Prepare the project**
   - Right-click your .uproject file
   - Generate Visual Studio project files
2. **Build the project (including the plugin)**
   - Open solution (`.sln`)
   - Choose `Development Editor` as your target.
   - Build

### Plugin
Otherwise, if you want to use the plugin in your existing project:

1. **Copy the plugin to your project**
   - Copy `MCPGameProject/Plugins/UnrealMCP` to your project's Plugins folder

2. **Enable the plugin**
   - Edit > Plugins
   - Find "UnrealMCP" in Editor category
   - Enable the plugin
   - Restart editor when prompted

3. **Build the plugin**
   - Right-click your .uproject file
   - Generate Visual Studio project files
   - Open solution (`.sln)
   - Build with your target platform and output settings

### Python Setup

See [Python/README.md](Python/README.md) for detailed Python setup instructions.

### LLM configuration for NPC simulation

The agent runtime uses two models, configured independently in `Python/.env`
(git-ignored): a **decision LLM** (chooses what each NPC does) and a **vision
model** (turns each screenshot into landmarks/characters). Each can be a cloud
provider **or** a local [Ollama](https://ollama.com) model.

#### Cloud (Haiku for both decisions and vision)

Haiku 4.5 is multimodal, so one provider and one key cover **both** roles — this is the simplest
cloud setup:

```dotenv
LLM_PROVIDER=anthropic            # decisions: anthropic | openai | ollama
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001

VISION_PROVIDER=anthropic         # observations: anthropic | gemini | ollama
ANTHROPIC_VISION_MODEL=claude-haiku-4-5-20251001
```

Gemini stays selectable for vision (`VISION_PROVIDER=gemini`, `GEMINI_API_KEY`,
`GEMINI_MODEL=gemini-2.5-flash-lite`) if you prefer it. For OpenAI decisions instead, set
`LLM_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL`.
The OpenAI path uses the Responses HTTP API directly through `requests` instead
of the OpenAI Python SDK, avoiding a Python 3.14 compatibility issue in the
SDK/Pydantic stack while keeping runtime behavior the same.

#### OpenRouter (what the live runs use, 2026-11)

One key, any model. The SR83_P–SR94_P runs used Claude Sonnet 5 for decisions and Qwen for vision:

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=anthropic/claude-sonnet-5
VISION_PROVIDER=openrouter
OPENROUTER_VISION_MODEL=qwen/qwen3.7-flash
```

The vision provider can answer 429 ("too many requests"). A failed look is logged and recorded,
not retried; the eye memory (#122) removes most repeat calls.

#### Fully local (Ollama)

Run both the decision LLM and vision on a local Ollama model — no API keys, no
cloud calls. A single **multimodal** model (e.g. `qwen3.5:4b`, which is both
vision- and tool-capable) can serve both roles:

```dotenv
LLM_PROVIDER=ollama
VISION_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3.5:4b           # decision LLM
VISION_MODEL=qwen3.5:4b           # observations — must be a vision-capable model
```

Prerequisites: Ollama running locally with the model pulled
(`ollama pull qwen3.5:4b`). The adapter (`Python/agent_runtime/ollama_adapter.py`)
talks to Ollama's native `/api/chat`, disables "thinking", and forces JSON
output. The first call is slow while the model loads into VRAM — a
`qwen3.5:4b: model LOADED in Xs` line appears on the PIE overlay — and warm calls
are much faster. Switch back to cloud at any time by setting
`LLM_PROVIDER` / `VISION_PROVIDER` to their cloud values.

Settings are re-read from `.env` before each batch of LLM calls.

The sim runs standalone — no MCP client configuration needed. Start it with
`Python/start_sim.bat` or `python Python/sim_runner.py`; it talks to Unreal over
raw TCP on port 55557 via `agent_runtime/unreal_connection.py`.


## Changes from Upstream

This fork adds the following on top of [chongdashu/unreal-mcp](https://github.com/chongdashu/unreal-mcp):

### Character Interaction System
A full NPC character command system built on a new `UAPCCharacterComponent`:
- **Messaging** â€” send messages to characters and read their replies
- **Memory** â€” per-character key-value fact store
- **Status queries** â€” health, inventory, location, AI state, current action, nearby actors
- **Action commands** â€” move to location/actor, follow, stop, look at, pickup, drop, say, play animation, set AI state
- **Blueprint events** â€” `OnMessageReceived`, `OnSayRequested`, `OnAIStateChanged`, `OnInteractRequested`

See [Docs/character_system.md](Docs/character_system.md) for full details.

### Camera Capture System
A `CameraCaptureActor` and MCP tool that lets AI assistants take and analyze in-game screenshots during PIE:
- **Scene snapshots** â€” triggers a `SceneCaptureComponent2D` render and saves a PNG to the project folder
- **Timestamped filenames** â€” each capture is saved as `<ActorName>_<YYYYMMDD>_<HHMMSS>.png`, so no captures are overwritten
- **Auto-discovery** â€” if no actor name is passed, the first `CameraCaptureActor` in the level is used
- **Image analysis** â€” AI clients can read the saved image and describe or reason about the scene

### AI RPG Agent Simulation
A first-pass agentic NPC simulation layer driven by an LLM-controlled Agent Manager running inside the Python MCP server. See [`MASTER_PLAN.md`](MASTER_PLAN.md) for the complete design.
- **Agent Manager** â€” start/stop/pause an autonomous simulation loop from the CLI
- **Live agent binding** â€” active agents bind to named Unreal actors or spawn from configured Blueprint classes
- **Multi-tier agents** â€” Hero (full LLM), Simulated (event-driven LLM), and Lightweight (no LLM unless explicitly configured)
- **World-state driven** â€” agents observe Unreal structured data; screenshots used selectively
- **Validated action pipeline** â€” LLM decisions are schema-validated before any Unreal command executes
- **Level-aware loading** â€” agents live under `Python/worlds/<LevelName>/agents/` and are loaded automatically based on the currently open Unreal level; no config field needed
- **Web cockpit** â€” local FastAPI app (`Python/web_ui/`): drive the sim (`/sim` — start/stop/step + live decision feed), manage provider profiles (`/providers`), and edit config (`/settings`). Launch with `start_sim.bat` (alongside the sim engine). NPC scaffolding moved to the `/create-npc` skill; the legacy `npc_builder` app was removed 2026-06-28.
- **Sim modes: `play` and `survey` (#102)** - `play` (default) runs the APCs on their agendas; `survey` maps unknown ground cell by cell. The first-version `explore` mode is retired; see [Explore Mode](#-explore-mode-vlm-spatial-mapping) for the idea it came from.
- **Local model support (Ollama)** â€” run both the decision LLM and vision perception fully locally on an Ollama model (e.g. the multimodal `qwen3.5:4b`) with no cloud API keys. Decision and vision providers are selected independently in `Python/.env`. See [LLM configuration for NPC simulation](#llm-configuration-for-npc-simulation).

### Spatial knowledge, memory & navigation

A cognitive layer the agents build and share as they run (verified live in PIE, 2026-06-26):

- **Landmarks (authored ground truth, 2026-07-08)** â€” drop a `Landmark_<owner>_<name>`-labeled
  actor in the level and the sim treats it as an authored place: scanned at sim start and by the
  `/map` **Sync world** button (which reports exactly what applied and flags near-miss labels).
  The level is the single source of truth — moving the actor moves the place.
- **Named-place navigation** â€” `walk_to "<place name>"` resolves a place name â†’ grid cell â†’ world location (`PlaceDB.find_named_cell` + `WorldGrid.cell_center`), so an agent navigates to a stated destination instead of idling. Unknown names fall back gracefully.
- **Shared world map (place cells)** â€” a SQLite `world_places.db` of named grid cells + compass-indexed landmark observations, **shared across all agents** (one agent's discoveries steer the others). `known_places` surfaces the named-place map (bearing + distance, nearest first) to each agent so it can pick a destination by name.
- **Episodic + social memory (per agent)** â€” `episodes.jsonl` records structured per-tick events `{world_time, grid_cell, place, saw[], action, outcome}`; `social.json` tracks acquaintances `{first_met, last_seen, meet_count, sentiment}` from perceived characters and speech. Recall blends recency + spatial proximity + social ties â€” beating the flat 30-item `memory.json` window for long/overnight runs.
- **Deterministic identity recognition (#44)** â€” the vision model labels every figure "unknown person"; `agent_runtime/recognition.py` reconciles that against engine-known positions (geometry, not a model guess) so an APC recognizes another APC it has already met instead of every encounter reading as a first meeting.
- **Authored agendas + daily ledger (#36)** â€” `agenda.json` per agent is stable, user-authored schedule input (tasks, places, completion policy); `agent_runtime/agenda.py` derives runtime task state and a chronological ledger from it deterministically each tick, separate from the authored file.
- **Behavioral guardrail facts, not code-side blocking** â€” when an agent does something a simple rule should have prevented (wandering off-path, drifting farther from a destination), the fix is a louder deterministic fact in the decision prompt (`FOOTING: <surface>`, `PROGRESS WARNING`) plus an explicit line in `rules.md`, not a validator that blocks the action. Judgment stays with the LLM; code's job is making the relevant fact impossible to miss.
- **Place-cell sweep (no dedicated maintenance role)** - the old `"role": "maintenance"` system worker was retired (#11.1). Any APC runs the sweep (walk to the stand point, look around, name the cell) when it needs a community place cell.
- **Perception-guided exploration (#77/#78/#26, verified live SR43-SR45 2026-08-19)** — the APC's own eyes
  outrank the navmesh. Perception reports `ground_ahead` (footing the APC would stand on a few steps out)
  and `path_ahead` (`open|dead_end|blocked`); an eyes cache files those per compass word while the APC
  stays on the spot, so a direction line reads "your own eyes saw: grass ahead, the way ahead DEAD-ENDS".
  Refusal is two-scale: `refuse_cell` blocks a whole 30 m cell (corn field, water), `scope: "spot"` writes a
  9 m **no-go patch** (`no_go_patches`) that poisons one bad yard while the cell stays a survey target.
  Two consecutive opposite-heading legs count a **bounce**, stated as a fact once it repeats. All facts,
  no blockers — nothing in code stops a step onto refused ground; the prompt and the map state the record.
  A cell, once surveyed, is never re-offered (`SURVEY_STALE_REFRESH = False`).
- **Perception dataset recorder (#79)** — every perceived frame is written as a training pair the moment it
  is perceived: one JSON line per image to `agents/<id>/observations/perception_log.jsonl` (caption,
  landmarks, footing, `ground_ahead`, `path_ahead`, heading, cell, model, `sim_run`, and `error` when
  perception fails — recorded, not hidden). Wired into all four perceive sites (tick, wake sweep, survey
  sweep, legacy explore). Before this only the ~21 survey composites kept their text while the per-tick
  stream threw its labels away. Dataset packaging/dedup/splits are a build-time job over the JSONL.
- **Refused ground on `/map` (#80)** — refused cells paint a red diagonal hatch over whatever survey state
  they also carry, no-go patches draw as dashed red circles at their true radius, and both tooltips lead
  with `REFUSED by <who>: <reason> (<world time>)`. Read-only: withdrawing a refusal stays the APC's own
  `allow_cell` act, never a map click.
- **`.env` config store** â€” `agent_runtime/config_store.py` reads/writes provider/model settings with secrets shown set/unset only (backs a future settings UI; no hand-editing `.env`).

### Standalone runner & web cockpit

- **Standalone sim runner** (`Python/sim_runner.py`) â€” runs the simulation in its **own process,
  independent of Claude/MCP** (the "runs overnight without Claude open" host). It owns the
  AgentManager and the single Unreal socket, and exposes a localhost HTTP control surface
  (`/status`, `/start`, `/stop`, `/tick`); MCP tools and the web UI can *attach* via
  `agent_runtime.runner_client.RunnerClient` instead of hosting the manager themselves. Run it with
  `python sim_runner.py --port 8777` (Unreal in PIE). The control API + client are offline-tested.
- **Sim cockpit** (`/sim` in the web app) â€” drive the running sim from the browser: status panel,
  Start/Stop, single-tick **Step** (debugging), and a live decision-log feed (poll-based, with a
  **Clear feed** button + per-event local timestamps). Proxies to the sim engine via `RunnerClient`.
- **Provider profiles** (`/providers` in the web app) â€” create/edit/delete named `{provider, model}`
  profiles and assign them to the **decision** and **vision** roles. Profiles live in a `config.json`
  and are **compiled down to the plain `.env` keys** the runtime already reads (`agent_runtime/provider_profiles.py`),
  so `llm_router`/`perception` are untouched and the sim picks up changes without a restart. No secrets
  in profiles â€” keys stay in `.env`.
- **Web settings page** (`/settings` in the web app) â€” manage provider/model config (the Ollama vs
  cloud switch, models) through the UI instead of hand-editing `.env`. Secret keys show only
  whether they are *set*; a blank secret field is left untouched. Backed by `agent_runtime/config_store.py`.

### Offline test suite

> **State 2026-11-11:** the suite has not been run or updated since the place work of #115–#123
> (the user's rule: proof is a live run). Backlog #107 lists scripts that already failed on an
> untouched HEAD. Do not read a green or red result here as the state of the sim.

The agent-runtime logic is covered by offline tests that stub Unreal entirely (no editor, no network, no LLM call) â€” the loop-safe surface for automated/unattended development:

```bash
cd Python
.venv/Scripts/python.exe scripts/run_tests.py            # one PASS/FAIL across the suite
.venv/Scripts/python.exe scripts/run_tests.py --only test_place_resolver   # a single test
```

The socket-based `scripts/{actors,node,blueprints}` scripts are integration demos that need a live editor and are excluded from this suite.

---

## ðŸŽ­ Character Interaction System

The plugin includes a full NPC character command system. The C++ side — the `UAPCCharacterComponent`,
its Blueprint events, and the `command_character_*` / `get_character_*` commands — is live and is how
the sim drives NPCs (the runtime reaches it over the raw socket via `UnrealBridge`).

> **Note (2026-06-28):** the Python examples below were the **retired** MCP wrapper tools
> (`character_tools.py`, removed with the other editor-authoring tools — see the Overview note). They
> are kept here to show the **command shapes**; the commands themselves still exist in C++ over the
> socket on `:55557`, but they are no longer exposed as Python MCP tools.

### Quick setup per NPC
1. Add `UAPCCharacterComponent` to your NPC Blueprint
2. Assign an AI Controller (required for move/follow/stop)
3. Implement the Blueprint events you want: `OnMessageReceived`, `OnSayRequested`, `OnAIStateChanged`, `OnInteractRequested`

### Example
```python
# Send a message to an NPC
send_character_message("GuardNPC", "The player was spotted near the north gate")

# Command the NPC to walk somewhere
command_character_move_to("GuardNPC", location=[1000, 500, 0])

# Make the NPC pick up a weapon
command_character_pickup("GuardNPC", "Sword_01")

# Make the NPC say something (fires OnSayRequested in Blueprint)
command_character_say("GuardNPC", "Halt! Who goes there?")

# Read replies the NPC has queued in their outbox
get_character_messages("GuardNPC", source="outbox", clear=True)
```

See [Docs/character_system.md](Docs/character_system.md) for the full command reference, component property list, and setup checklist.

---

## ðŸ¤– AI RPG Agent Simulation

> **Status: Prototype** â€” See [`MASTER_PLAN.md`](MASTER_PLAN.md) for the full design. The live task list is [`plan/backlog.md`](plan/backlog.md).

The simulation layer lets an LLM (Claude, OpenAI, or a local model) autonomously drive NPCs inside a live Unreal session.

### Architecture

```
Web cockpit / curl / Claude (dev mode)
        â”‚  localhost HTTP (:8777)
        â–¼
sim_runner.py  â”€â”€â”€ Agent Manager + Simulation Harness
        â”‚              â”œâ”€ AgentRegistry / MemoryStore
        â”‚              â”œâ”€ LLMRouter (per-agent model selection)
        â”‚              â””â”€ ActionValidator (schema + allowlist)
        â”‚  Unreal commands (raw TCP :55557)
        â–¼
Unreal C++ plugin (UnrealMCP) â†’ Unreal Editor / PIE
```

### Sim control surface (runner HTTP API on `:8777`)

| Endpoint | Description |
|------|-------------|
| `POST /start` | Start the autonomous agent loop (`tick_seconds`, `active_agents`, `mode`: `play` (default) or `survey`). Each start puts every APC back on its start transform. |
| `POST /stop` | Stop the loop |
| `POST /pause` / `POST /resume` | Pause or resume without losing state |
| `GET /status` | Live status of the running sim |
| `GET /agents` | Browse active agents |
| `POST /tick` | Manually pulse the loop (single step) |
| `GET /events` | Tail the world event log |
| `POST /reset_day` | Restart the sim day from morning (memories kept) |

### Smoke test

With Unreal running in PIE and the runner up (`start_sim.bat`):

```bash
curl -X POST http://127.0.0.1:8777/start -H "Content-Type: application/json" -d '{"tick_seconds":1,"mode":"play","active_agents":["dufus"]}'
curl http://127.0.0.1:8777/events?limit=10
curl -X POST http://127.0.0.1:8777/stop
```

Expected: Dufus binds to his actor in MCP_World; each tick the agent captures a camera PNG internally (via `UnrealBridge`), and the LLM decision loop returns a validated action visible in `/events` and the cockpit feed. Generated captures and decision logs are ignored by git.

### Agent tiers

| Tier | Examples | LLM usage |
|------|----------|-----------|
| 1 â€” Hero | Main villain, quest giver, lead NPC | Full memory + goal reasoning every tick |
| 2 â€” Simulated | Dufus, innkeeper, guard captain | LLM on every tick at normal cadence |
| 3 â€” Lightweight | Villagers, animals, basic guards | Behavior Tree; LLM only on promotion |

---

## ðŸ§­ Explore Mode (VLM spatial mapping)

> **Status: Working in PIE** â€” verified end-to-end 2026-06-07 (an avatar walked the town's west edge and built a labeled map).

> **State 2026-11-11:** `explore` is no longer a sim mode. The runner accepts `play` and `survey`
> (#102); any other word falls back to `play` with a warning. Mapping an unknown world is now the
> `survey` mode. This section describes the first version and is kept for the idea.

A second simulation mode where the avatar **discovers a world by looking at it and walking it**, rather than acting on pre-authored knowledge. The thesis: distil Unreal's thousands of engine actors into an *engine-agnostic* representation â€” metric coordinates + vision-derived semantic labels + a nav graph â€” so the same pipeline would drive a real robot with a camera.

### The tick (deterministic routing; the model only perceives)

```
observe (own pose + camera frame)
  â†’ perceptual-hash diff-gate (skip re-labelling an unchanged view)
  â†’ VLM.perceive()              # frame â†’ {landmarks, characters, caption}  (Gemini or local Ollama)
  â†’ SpatialMap.ingest()          # write labels into the current grid cell
  â†’ explorer.next_target()       # pick nearest unexplored frontier  (CODE, not LLM)
  â†’ command_character_move_to()  # walk there
```

The VLM is used **only** for perception (turning pixels into labels). Movement is a deterministic frontier sweep â€” cheap, predictable coverage, no LLM in the control loop.

### The map (`worlds/<level>/agents/<id>/spatial_map.json`)

Per-agent (egocentric). Grid cells keyed `"gx,gy"` (`floor(x / cell_size)`, default 400 cm), each holding the landmark tags seen from that cell (with confidence/distance/bearing) and the `edges` traversed to neighbors. Place coordinates are derived on demand from the labels â€” nothing Unreal-specific is stored.

### Requirements (learned the hard way)

- **PIE must be running** â€” the AIController only possesses the avatar in Play.
- **Walkable NavMesh under the avatar** â€” a `NavMeshBoundsVolume` that is *tall enough* (its Z extent must clear the floor by more than the agent height; a too-thin volume builds no navmesh and the avatar silently won't move). The avatar must be **standing on green** (on the mesh), not on grass/dirt or floating.
- **A vision model** in `Python/.env` â€” either Gemini (`VISION_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-2.5-flash-lite`) or a local Ollama vision model (`VISION_PROVIDER=ollama`, `OLLAMA_HOST`, `VISION_MODEL=qwen3.5:4b`). See [LLM configuration](#llm-configuration-for-npc-simulation).
- **Pillow** installed (enables the diff-gate; without it every frame is re-perceived).

### Smoke test

```bash
curl -X POST http://127.0.0.1:8777/start -d '{"tick_seconds":10,"active_agents":["maren"],"mode":"explore"}'
curl -X POST http://127.0.0.1:8777/tick      # observe -> perceive -> map -> pick frontier -> walk
curl -X POST http://127.0.0.1:8777/stop
```

Expected: each tick the agent's `cells_visited` climbs, `spatial_map.json` fills with landmark-tagged cells linked by nav edges, and the avatar walks frontier-to-frontier. Delete `spatial_map.json` to start a fresh map.

---

## License
MIT

## Questions

For questions, you can reach me on X/Twitter: [@TheDrizzelz2024](https://x.com/TheDrizzelz2024)
