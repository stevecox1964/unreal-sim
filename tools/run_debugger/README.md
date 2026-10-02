# Run Debugger

A visual debugger for sim runs. It reads the logs of one run (for example `SR45`) and makes a
replay you can scrub through. It shows what each APC did over time, every model call, and the
calls that were wasted.

## Quick start

To run a new analysis, open PowerShell and paste both lines. Change `SR45` to your run.

```powershell
cd "unreal-sim\tools\run_debugger"
uv run python render.py SR45
```

Then open the file it prints, for example:

```
unreal-sim\tools\run_debugger\run_analysis\SR45_20261002_113404.html
```

Double-click it. It opens in your browser. It needs no server and no internet.

## Commands

Run every command from this folder:

```powershell
cd "unreal-sim\tools\run_debugger"
```

| Command | Output |
|---|---|
| `uv run python render.py SR45` | HTML page (default, about 1 second) |
| `uv run python render.py SR45 --video` | MP4 video, 480p (a few minutes) |
| `uv run python render.py SR45 --video h` | MP4 video, 1080p |
| `uv run python analyze.py SR45` | JSON data only, in `out\SR45.json` |

The output file name is `SR<n>_<YYYYMMDD_HHMMSS>.html` (or `.mp4`). The date and time are when
you made the file, not when the run happened. All outputs go to:

```
unreal-sim\tools\run_debugger\run_analysis\
```

### Which run names exist?

Runs are named `SR<n>`. The current number is in:

```
unreal-sim\Python\worlds\MCP_World\sim_run.json
```

Every run in `agent_decisions.log` can be replayed.

## Using the HTML page

### Controls

| Control | What it does |
|---|---|
| **Play / Pause** or **Space** | Plays the run |
| **Speed** (1× to 60×) | How many run-seconds pass per real second |
| **Scrub bar** | Drag to any moment |
| **"stop at flagged calls"** | Playback pauses on each bad call, so you can read it. On by default |
| **→ / ←** or **flag ▶ / ◀ flag** | Jump to the next or previous flagged call |
| **Shift + → / ←** | Move 5 seconds |
| **Mouse wheel** or **＋ / －** | Zoom the timeline in or out |
| **Drag the timeline** | Pan left or right |
| **Click the minimap** (top strip) | Jump to that part of the run |
| **Click a block, icon, or feed line** | Show its full details in **Selected** |

### What you see

Each APC has one lane. Everything sits where it really happened in time.

| Mark | Meaning |
|---|---|
| 👁 blue block | **Looking**: screenshot and senses |
| 💭 gold block | **Thinking**: one decide API call. Width = seconds the model took |
| green line | **Walking** after a `walk_to` |
| grey line | **Waiting** |
| 👣 | Action was walk |
| 💬 | Action was talk |
| 🔭 | Action was observe |
| • | Other action (wait, idle, ...) |
| ⚑ | Interrupt started or ended |
| 📷 | Survey look |
| ★ | Wake-up API call |
| orange outline | **Redundant** call |
| red outline | **Retry** or failed call |
| purple outline | **Loop** |
| API lane (bottom of each lane) | Every model call: decide, vision, wake, chat, ask. A red outline means the call failed |

### The three panels

- **At the playhead**: what each APC is doing right now (looking, thinking, walking, or
  waiting), its last thought, and any API call in flight.
- **Selected**: the full details of what you clicked. For a decision, it shows the thought, why
  it was flagged, the timings, and the call before it. For an API call, it shows the model,
  seconds, tokens, and error.
- **Feed**: every event in time order. It follows the playhead. Click a line to jump there.

## How calls are flagged

One decision row in the log = one decide API call. A call gets one flag, checked in this order:

1. **Retry**: the result was not `success`, or the row has an error.
2. **Redundant**: the same action, direction, and cell as the call before it. Or the thought is
   85% or more the same as the call before it.
3. **Loop**: the APC went back to a cell it left within its last 6 calls.

"Wasted" time = the model seconds spent on flagged calls.

These are simple rules. They can flag a real, needed repeat. Use them as a pointer to look
closer, not as a verdict. To change them, edit `LOOP_WINDOW`, `SIMILAR`, and `_flag()` in
`analyze.py`.

## Where the data comes from

All logs are in:

```
unreal-sim\Python\worlds\MCP_World\logs\
```

| File | What it gives | Notes |
|---|---|---|
| `agent_decisions.log` | Each decision: action, thought, cell, look/think/act timing; interrupts and survey looks | Keeps all runs |
| `api_calls\SR<n>.jsonl` | Every model call: purpose, model, ms, tokens, ok/error | One file per run. New on 2026-10-02, so older runs have an empty API lane. Only the newest 50 runs are kept: when a new run starts, the oldest file is deleted. Change `KEEP_RUNS` in `Python\agent_runtime\api_call_log.py` |
| `sim_runner.log` | Model name and wake-up calls | Overwritten every run, so it only covers the latest run |

### Timing assumption

A decision row is logged when its action finishes. The page rebuilds each cycle backward from
that time: look (`observe_ms`) → think (`llm_ms`) → act (`act_ms`). This looks right, but it is
not proven. The first call of a run often has no timing, so it shows as zero width.

## Files

| File | What it is |
|---|---|
| `render.py` | Run this. It calls `analyze.py`, then writes the page or the video |
| `analyze.py` | Reads the logs and writes `out\<run>.json` |
| `page.html` | The HTML page template. The run data is pasted in at `/*DATA*/` |
| `replay.py` | The Manim video scene (only for `--video`) |
| `run_analysis\` | Your pages and videos |
| `out\`, `media\` | Working files. Safe to delete |

## Setup (one time, already done)

This folder is its own uv project on Python 3.14, with Manim Community v0.21.0.

```powershell
cd "unreal-sim\tools\run_debugger"
uv sync
```

The HTML page only needs Python. Manim is only for `--video`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `No decision rows for SR99` | That run has no decisions in `agent_decisions.log`. Check the run name |
| API lane is missing | The run is older than 2026-10-02, or it is older than the newest 50 runs, so it has no `api_calls\SR<n>.jsonl` file |
| Model name says "not logged" | `sim_runner.log` only holds the latest run, and the run has no API log |
| Page is blank | Open the browser console (F12) and look for a red error |
| `pydub` SyntaxWarning in the video build | Harmless. `render.py` hides it |
