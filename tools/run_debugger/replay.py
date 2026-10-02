"""Manim visual-debug replay on a real-time axis. Use render.py, not this file, to make a video.

One lane per APC. Every decision cycle is drawn where it really happened:
  eye icon + blue block    = LOOKING (screenshot + senses)
  cloud icon + gold block  = THINKING = one decide API call; width = seconds the model took
  icon under the lane      = what it DID (feet = walk, speech = talk, eye = observe)
  green line               = walking after a walk_to;  grey line = waiting
  triangle / small eye     = interrupt / survey look;  star = wake-up API call
A playhead sweeps the run. It stops at the costliest flagged calls and explains them.
"""
import json
import os
import textwrap

from manim import *

FLAG = {"redundant": ORANGE, "retry": RED, "loop": PURPLE}
LABEL = {"redundant": "REDUNDANT", "retry": "RETRY", "loop": "LOOP"}
LOOK, THINK, WALK, WAIT = BLUE_C, GOLD, GREEN_C, GREY_D
S = 0.12            # scene units per run second
PH = -1.0           # playhead x
SPEED = 45          # run seconds per video second while sweeping
MAX_CARDS = 6
LANE_GAP = 1.9


# ---------- icons (drawn from shapes so they render everywhere) ----------
def eye(c=LOOK, s=1.0):
    return VGroup(Ellipse(0.34, 0.18, color=c, stroke_width=2), Dot(radius=0.05, color=c)).scale(s)


def cloud(c=THINK):
    return VGroup(
        Ellipse(0.36, 0.22, color=c, fill_opacity=0.9, stroke_width=0),
        Dot(radius=0.035, color=c).shift(DOWN * 0.15 + LEFT * 0.12),
        Dot(radius=0.022, color=c).shift(DOWN * 0.22 + LEFT * 0.18),
    )


def feet(c=WALK):
    a = Ellipse(0.07, 0.14, color=c, fill_opacity=1, stroke_width=0)
    return VGroup(a.copy().shift(LEFT * 0.05 + DOWN * 0.04), a.copy().shift(RIGHT * 0.05 + UP * 0.04))


def speech(c=TEAL_C):
    box = RoundedRectangle(corner_radius=0.06, width=0.32, height=0.2, color=c, stroke_width=2)
    tail = Polygon([-0.06, -0.1, 0], [0.02, -0.1, 0], [-0.1, -0.18, 0], color=c, stroke_width=2)
    return VGroup(box, tail)


def action_icon(action):
    return {"walk_to": feet(), "speak_to": speech(), "observe": eye(TEAL_C)}.get(action, Dot(radius=0.06, color=WHITE))


def event_icon(kind):
    if kind == "interrupt":
        return Triangle(color=PINK, fill_opacity=1, stroke_width=0).scale(0.09)
    return eye(TEAL_C, 0.6)


def wrap(text, width, lines=2):
    return "\n".join(textwrap.wrap(text, width)[:lines])


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


class RunReplay(Scene):
    def construct(self):
        run = os.environ.get("RUN", "SR65")
        data = json.load(open(f"out/{run}.json", encoding="utf8"))
        agents, dur = data["agents"], data["duration_s"]
        model = ", ".join(data["models"]) or "model name not logged for this run"

        # ---------- intro: legend ----------
        title = Text(f"{run} replay  ({mmss(dur)} of sim time)", font_size=32).to_edge(UP, buff=0.2)
        sub = Text(model, font_size=18, color=GREY_B).next_to(title, DOWN, buff=0.08)
        rows = [
            (eye(), "Looking: screenshot + senses (blue block)"),
            (cloud(), "Thinking: one decide API call to the model (gold block, width = seconds)"),
            (feet(), "Walking (green line after the block)"),
            (speech(), "Talking"),
            (eye(TEAL_C), "Observe action, or a survey look"),
            (event_icon("interrupt"), "Interrupt started / ended"),
            (Star(color=YELLOW, fill_opacity=1).scale(0.12), "Wake-up API call"),
            (Dot(radius=0.06, color=WHITE), "Other action (wait, idle, ...)"),
            (VGroup(*[Square(0.18, color=c, fill_opacity=1) for c in FLAG.values()]).arrange(RIGHT, buff=0.08),
             "Flagged call: redundant / retry / loop"),
        ]
        legend = VGroup(*[VGroup(i, Text(t, font_size=22)).arrange(RIGHT, buff=0.3) for i, t in rows])
        legend.arrange(DOWN, aligned_edge=LEFT, buff=0.22).move_to(DOWN * 0.3)
        self.play(FadeIn(title), FadeIn(sub), FadeIn(legend))
        self.wait(4)
        self.play(FadeOut(legend))

        # ---------- minimap: whole run, flagged calls marked ----------
        mm_w, mm_x0 = 11.0, -5.0
        mm_s = mm_w / max(dur, 1)
        names = list(agents)
        mini = VGroup()
        for k, name in enumerate(names):
            y = 2.55 - k * 0.22
            mini.add(Line([mm_x0, y, 0], [mm_x0 + mm_w, y, 0], color=GREY_D, stroke_width=2))
            for c in agents[name]["calls"]:
                a, b = c["think"]
                col = FLAG.get(c["flag"], GREY_B)
                mini.add(Rectangle(width=max((b - a) * mm_s, 0.02), height=0.14, fill_color=col,
                                   fill_opacity=1, stroke_width=0).move_to([mm_x0 + (a + b) / 2 * mm_s, y, 0]))
            mini.add(Text(name, font_size=14, color=GREY_B).next_to([mm_x0, y, 0], LEFT, buff=0.1))

        # ---------- lanes, built with run-second 0 at the playhead ----------
        x = lambda t: PH + t * S
        track = VGroup()
        anchor = Dot(radius=0.001, fill_opacity=0).move_to([x(0), 0, 0])
        track.add(anchor)
        lane_y = {n: 1.2 - k * LANE_GAP for k, n in enumerate(names)}
        for name in names:
            y, a = lane_y[name], agents[name]
            track.add(Line([x(0), y, 0], [x(dur), y, 0], color=WAIT, stroke_width=2))
            calls = a["calls"]
            for j, c in enumerate(calls):
                nxt = calls[j + 1]["look"][0] if j + 1 < len(calls) else c["act"][1]
                if c["action"] == "walk_to" and c["moved_cm"] and nxt > c["act"][1]:
                    track.add(Line([x(c["act"][1]), y, 0], [x(nxt), y, 0], color=WALK, stroke_width=6))
                for (s0, s1), col in ((c["look"], LOOK), (c["think"], THINK)):
                    if s1 > s0:
                        track.add(Rectangle(width=(s1 - s0) * S, height=0.32, fill_color=col, fill_opacity=0.85,
                                            stroke_width=0).move_to([x((s0 + s1) / 2), y, 0]))
                if c["flag"]:
                    s0, s1 = c["think"]
                    track.add(Rectangle(width=max((s1 - s0) * S, 0.1) + 0.06, height=0.42, color=FLAG[c["flag"]],
                                        stroke_width=4).move_to([x((s0 + s1) / 2), y, 0]))
                if c["look"][1] > c["look"][0]:
                    track.add(eye().move_to([x(c["look"][0]) - 0.1, y + 0.42, 0]))
                if c["think"][1] > c["think"][0]:
                    track.add(cloud(FLAG.get(c["flag"], THINK)).move_to([x(sum(c["think"]) / 2), y + 0.45, 0]))
                track.add(action_icon(c["action"]).move_to([x(c["act"][1]) + 0.12, y - 0.38, 0]))
            for e in a["events"]:
                track.add(event_icon(e["kind"]).move_to([x(e["t"]), y - 0.62, 0]))
            for w in a["wakes"]:
                track.add(Star(color=YELLOW, fill_opacity=1).scale(0.12).move_to([x(w["t"]), y + 0.45, 0]))
        axis_y = lane_y[names[-1]] - 0.95
        track.add(Line([x(0), axis_y, 0], [x(dur), axis_y, 0], color=GREY_C, stroke_width=1))
        for t in range(0, int(dur) + 1, 30):
            track.add(Line([x(t), axis_y, 0], [x(t), axis_y - 0.08, 0], color=GREY_C, stroke_width=1))
            track.add(Text(mmss(t), font_size=14, color=GREY_C).move_to([x(t), axis_y - 0.22, 0]))

        # Left mask keeps lane labels readable while the track scrolls under them.
        mask = Rectangle(width=1.6, height=4.4, fill_color=BLACK, fill_opacity=1, stroke_width=0)
        mask.move_to([-7.1 + 0.8, (lane_y[names[0]] + axis_y) / 2, 0]).set_z_index(5)
        labels = VGroup(*[Text(n, font_size=20).move_to([-6.3, lane_y[n], 0]) for n in names]).set_z_index(6)
        playhead = DashedLine([PH, lane_y[names[0]] + 0.75, 0], [PH, axis_y, 0], color=WHITE, stroke_width=2)

        now = ValueTracker(0)
        track.add_updater(lambda m: m.shift(RIGHT * (x(0) - now.get_value() * S - anchor.get_x())))
        win = 14.2 / S
        view = Rectangle(width=win * mm_s, height=0.22 * len(names) + 0.1, color=WHITE, stroke_width=1.5)
        view.add_updater(lambda m: m.move_to([mm_x0 + (now.get_value() - (PH + 7.1) / S + win / 2) * mm_s,
                                              2.55 - 0.11 * (len(names) - 1), 0]))
        clock = Text("0:00", font_size=20, color=WHITE).next_to(playhead, UP, buff=0.05)
        clock.add_updater(lambda m: m.become(Text(mmss(now.get_value()), font_size=20)
                                             .next_to(playhead, UP, buff=0.05)))
        self.play(FadeIn(mini), FadeIn(view), FadeIn(track), FadeIn(mask), FadeIn(labels),
                  Create(playhead), FadeIn(clock))

        # ---------- sweep, stopping at the costliest flagged calls ----------
        flagged = [(n, c) for n, a in agents.items() for c in a["calls"] if c["flag"]]
        stops = sorted(sorted(flagged, key=lambda p: -p[1]["llm_ms"])[:MAX_CARDS], key=lambda p: p[1]["think"][1])
        for name, c in stops:
            t = c["think"][1]
            if t > now.get_value():
                self.play(now.animate.set_value(t), run_time=max((t - now.get_value()) / SPEED, 0.3), rate_func=linear)
            self.show_card(name, c, agents[name]["calls"])
        if dur > now.get_value():
            self.play(now.animate.set_value(dur), run_time=max((dur - now.get_value()) / SPEED, 0.3), rate_func=linear)

        # ---------- summary ----------
        tw = sum(a["wasted_s"] for a in agents.values())
        tt = sum(a["total_s"] for a in agents.values())
        lines = [
            Text(f"{sum(len(a['calls']) for a in agents.values())} decide API calls, "
                 f"{tt:.0f}s of model time, {tw:.0f}s ({100 * tw / tt if tt else 0:.0f}%) on flagged calls",
                 font_size=24, color=YELLOW),
            *[Text(f'{n}: retry {a["counts"]["retry"]}, redundant {a["counts"]["redundant"]}, '
                   f'loop {a["counts"]["loop"]}  ->  {a["wasted_s"]}s of {a["total_s"]}s', font_size=20)
              for n, a in agents.items()],
        ]
        summary = VGroup(*lines).arrange(DOWN, aligned_edge=LEFT, buff=0.15).to_edge(DOWN, buff=0.25).to_edge(LEFT, buff=0.4)
        self.play(FadeIn(summary))
        self.wait(4)

    def show_card(self, name, c, calls):
        col = FLAG[c["flag"]]
        prev = calls[c["i"] - 1] if c["i"] else None
        look_s, think_s = c["look"][1] - c["look"][0], c["think"][1] - c["think"][0]
        card = VGroup(
            Text(f'{name} at {c["time"]}  {LABEL[c["flag"]]}', font_size=22, color=col),
            Text(f'Looked {look_s:.1f}s, then the model thought {think_s:.1f}s, then: {c["action"]}  '
                 f'(cell {c["cell"]})', font_size=18),
            Text(f'Why flagged: {c["reason"]}', font_size=18),
            Text("Thought: " + wrap(f'"{c["thought"]}"', 110, 1), font_size=16, color=GREY_A),
        )
        if prev:
            card.add(Text("Before:  " + wrap(f'{prev["action"]} - "{prev["thought"]}"', 110, 1),
                          font_size=16, color=GREY_B))
        card.arrange(DOWN, aligned_edge=LEFT, buff=0.1)
        if card.width > 13.4:
            card.scale_to_fit_width(13.4)
        card.to_edge(DOWN, buff=0.15).to_edge(LEFT, buff=0.4)
        self.play(FadeIn(card), run_time=0.4)
        self.wait(3.5)
        self.play(FadeOut(card), run_time=0.3)
