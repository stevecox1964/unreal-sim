"""Browser tests for the /places editor page.

A real browser (the installed Edge or Chrome, headless) clicks the page; each
check then reads places.json from disk, so a button that looks right but
writes nothing fails. No Unreal, no network beyond localhost. Run:
    .venv\\Scripts\\python.exe scripts\\agent_runtime\\test_places_page.py

Needs the dev dependency ``playwright`` (``uv sync``); no browser download.
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # Python/
sys.path.insert(0, str(ROOT))

import uvicorn                                       # noqa: E402
from playwright.sync_api import sync_playwright      # noqa: E402
from agent_runtime.place_db import PlaceDB           # noqa: E402
from agent_runtime.world_grid import WorldGrid       # noqa: E402
import web_ui.main as wm                             # noqa: E402


def check(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"ok: {label}")


LEVEL = "TestWorld"
BOUNDS = {"min_x": -2000, "min_y": -2000, "max_x": 1999, "max_y": 1999}  # 10x10 cells
TRUCK = {"name": "the truck", "x": 1500.0, "y": -1500.0, "owner": "maren"}
DONUTS = "Don's Donuts"          # a runtime name in the world DB: a grey dot


def _world(tmp: str) -> Path:
    """One authored place (purple), one runtime place (grey), agents maren + dufus."""
    world = Path(tmp) / LEVEL
    for agent in ("maren", "dufus"):
        (world / "agents" / agent).mkdir(parents=True)
    (world / "world_grid.json").write_text(
        json.dumps({"cell_size": 400.0, "bounds": BOUNDS}), encoding="utf-8")
    (world / "places.json").write_text(json.dumps({"places": [TRUCK]}), encoding="utf-8")
    loc = WorldGrid.load(world / "world_grid.json").locate(-1500.0, -1500.0)
    PlaceDB(world / "world_places.db").add_owned_place(
        "dufus", loc["col"], loc["row"], DONUTS, dx=0.0, dy=0.0)
    return world


def _manifest(world: Path) -> dict:
    # The web app rewrites the file in place; a read can land mid-write.
    for _ in range(20):
        try:
            return json.loads((world / "places.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            time.sleep(0.05)
    check("places.json is valid JSON", False)


def _place(world: Path, name: str) -> dict | None:
    return next((p for p in _manifest(world)["places"] if p["name"] == name), None)


def _todo(world: Path) -> dict:
    return {t["place"]: t["items"] for t in _manifest(world).get("todo", [])}


def _serve() -> tuple[uvicorn.Server, str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(wm.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    check("the web app started", server.started)
    return server, f"http://127.0.0.1:{port}"


def _browser(pw):
    for channel in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(channel=channel, headless=True)
        except Exception:
            continue
    print("FAIL: no Edge or Chrome found for the browser tests")
    sys.exit(1)


class Page:
    """The few page moves the tests need, each one waiting for its result."""

    def __init__(self, page, world: Path):
        self.p = page
        self.world = world

    def eventually(self, label, cond, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline and not cond():
            self.p.wait_for_timeout(50)
        check(label, cond())

    def dots(self, cls: str) -> int:
        return self.p.locator(f"#marks .dot.{cls}").count()

    def labels(self) -> list[str]:
        return self.p.locator("#marks .name").all_text_contents()

    def msg(self) -> str:
        return self.p.locator("#msg").text_content() or ""

    def form(self) -> dict:
        return {k: self.p.input_value(f"#p-{k}")
                for k in ("name", "owner", "x", "y", "size", "items")}

    def chosen(self) -> str:
        """The text of the option the 'Choose a place' dropdown shows."""
        return self.p.locator("#pick option:checked").text_content() or ""

    def click_map(self, fx: float, fy: float):
        """Click the map at a fraction of its width/height."""
        box = self.p.locator("#map").bounding_box()
        self.p.locator("#map").click(position={"x": box["width"] * fx, "y": box["height"] * fy})

    def row_button(self, table: str, row_text: str, button: str):
        self.p.locator(f"#{table} tr", has_text=row_text).get_by_role(
            "button", name=button).click()


def test_load_hides_names_and_grey_dots(ui: Page):
    check("the place from places.json is one purple dot", ui.dots("authored") == 1)
    check("grey dots are hidden at page load", ui.dots("known") == 0)
    check("no name shows before a place is chosen", ui.labels() == [])
    check("the table lists the place",
          ui.p.locator("#place-rows tr", has_text="the truck").count() == 1)
    check("the dropdown offers a new place, the purple place and the grey place",
          ui.p.locator("#pick option").all_text_contents()
          == ["New place…", "the truck", DONUTS])

    ui.p.check("#show-known")
    check("the checkbox shows the grey dot", ui.dots("known") == 1)
    check("a grey dot shows no name before it is chosen", ui.labels() == [])
    ui.p.uncheck("#show-known")
    check("the checkbox hides the grey dot again", ui.dots("known") == 0)


def test_choose_place_then_move_rename_and_describe(ui: Page):
    ui.p.select_option("#pick", label="the truck")
    form = ui.form()
    check("a place chosen in the dropdown loads into the editor",
          form["name"] == "the truck" and form["owner"] == "maren"
          and float(form["x"]) == 1500.0 and float(form["y"]) == -1500.0)
    check("only the chosen place shows its name", ui.labels() == ["the truck"])
    check("a place in places.json can be deleted from the editor",
          ui.p.locator("#p-delete").is_visible())

    ui.p.click("#p-clear")
    check("Clear empties the editor", ui.form()["name"] == "" and ui.chosen() == "New place…")
    check("a new place has no Delete button", not ui.p.locator("#p-delete").is_visible())
    ui.p.locator("#marks .dot.authored").click()
    check("a purple dot click loads the same place",
          ui.form()["name"] == "the truck" and ui.chosen() == "the truck")

    # 25% across, 75% down a 3999 cm world from -2000 = (-1000, 999) cm.
    ui.click_map(0.25, 0.75)
    form = ui.form()
    check("a map click sets X and Y in world cm",
          abs(float(form["x"]) + 1000) <= 10 and abs(float(form["y"]) - 999) <= 10)
    check("a map click keeps the place in the editor", form["name"] == "the truck")

    ui.p.fill("#p-name", "the vegetable truck")
    ui.p.fill("#p-items", "Buy carrots\n\n  Talk to the seller  ")
    ui.p.click("#p-save")
    ui.eventually("the renamed place is saved to places.json",
                  lambda: _place(ui.world, "the vegetable truck") is not None)
    ui.eventually("the old name is gone (a rename is not a copy)",
                  lambda: [p["name"] for p in _manifest(ui.world)["places"]]
                  == ["the vegetable truck"])
    saved = _place(ui.world, "the vegetable truck")
    check("the move is saved, and the owner is kept",
          abs(saved["x"] + 1000) <= 10 and abs(saved["y"] - 999) <= 10
          and saved["owner"] == "maren")
    ui.eventually("the typed info is saved for the new name, one trimmed item per line",
                  lambda: _todo(ui.world)
                  == {"the vegetable truck": ["Buy carrots", "Talk to the seller"]})
    ui.eventually("the editor is empty again after the save",
                  lambda: ui.form()["name"] == "" and ui.chosen() == "New place…")


def test_add_place_and_bad_input(ui: Page):
    before = _manifest(ui.world)
    ui.click_map(0.75, 0.25)
    ui.p.click("#p-save")                                   # no name typed
    ui.eventually("a save with no name shows an error", lambda: "Save failed" in ui.msg())
    check("a failed save writes nothing", _manifest(ui.world) == before)

    ui.p.click("#p-clear")
    ui.p.fill("#p-name", "nowhere")
    ui.p.click("#p-save")                                   # no position, no info
    ui.eventually("a new place with no position shows an error",
                  lambda: "x and y" in ui.msg())
    check("a place with no position writes nothing", _manifest(ui.world) == before)

    ui.click_map(0.75, 0.25)
    ui.p.fill("#p-name", "bakery")
    ui.p.click("#p-save")
    ui.eventually("a new place is added to places.json",
                  lambda: _place(ui.world, "bakery") is not None)
    bakery = _place(ui.world, "bakery")
    check("the new place sits where the map was clicked, with no owner",
          abs(bakery["x"] - 999) <= 10 and abs(bakery["y"] + 1000) <= 10
          and "owner" not in bakery)
    check("a place saved with no info gets no list", "bakery" not in _todo(ui.world))
    ui.eventually("the map shows two purple dots", lambda: ui.dots("authored") == 2)


def test_grey_place_turns_purple_with_info(ui: Page):
    places_before = _manifest(ui.world)["places"]
    ui.p.select_option("#pick", label=DONUTS)
    form = ui.form()
    check("a grey place chosen in the dropdown loads into the editor",
          form["name"] == DONUTS and form["owner"] == "dufus" and form["x"] != "")
    check("the chosen grey place shows its dot and name while grey dots are hidden",
          ui.dots("known") == 1 and ui.labels() == [DONUTS])
    check("the position of an APC place cannot be typed over",
          ui.p.locator("#p-x").is_disabled() and ui.p.locator("#p-name").is_disabled())

    ui.click_map(0.5, 0.9)
    check("a map click does not move an APC place", ui.form()["x"] == form["x"])
    ui.p.click("#p-save")                                   # no info typed
    ui.eventually("a grey place with no info has nothing to save",
                  lambda: "Nothing to save" in ui.msg())
    check("nothing is written for it", DONUTS not in _todo(ui.world))

    ui.p.fill("#p-items", "Order a donut\nSit at a table")
    ui.p.click("#p-save")
    ui.eventually("the info for the grey place is saved in places.json",
                  lambda: _todo(ui.world).get(DONUTS) == ["Order a donut", "Sit at a table"])
    check("the APC position is not copied into places.json",
          _manifest(ui.world)["places"] == places_before)
    ui.eventually("the place is a purple dot now, with grey dots still hidden",
                  lambda: ui.dots("authored") == 3 and ui.dots("known") == 0)

    ui.row_button("place-rows", DONUTS, "Edit")
    check("Edit loads the saved info", ui.form()["items"] == "Order a donut\nSit at a table")
    ui.p.fill("#p-items", "Order a coffee")
    ui.p.click("#p-save")
    ui.eventually("edited info replaces the old info, and other lists stay",
                  lambda: _todo(ui.world).get(DONUTS) == ["Order a coffee"]
                  and len(_todo(ui.world)) == 2)


def test_delete(ui: Page):
    ui.p.once("dialog", lambda d: d.accept())
    ui.row_button("place-rows", "bakery", "Delete")
    ui.eventually("Delete removes the place from places.json",
                  lambda: _place(ui.world, "bakery") is None)
    check("Delete removes only that place",
          [p["name"] for p in _manifest(ui.world)["places"]] == ["the vegetable truck"])

    ui.p.select_option("#pick", label="the vegetable truck")
    ui.p.once("dialog", lambda d: d.accept())
    ui.p.click("#p-delete")
    ui.eventually("Delete in the editor removes the place and its info",
                  lambda: _manifest(ui.world)["places"] == []
                  and "the vegetable truck" not in _todo(ui.world))

    ui.p.select_option("#pick", label=DONUTS)
    ui.p.fill("#p-items", "")
    ui.p.click("#p-save")
    ui.eventually("info cleared for an APC place removes its list",
                  lambda: _todo(ui.world) == {})
    ui.eventually("the APC place is grey again: no purple dot is left",
                  lambda: ui.dots("authored") == 0)


def main():
    old = wm.WORLDS_DIR
    with tempfile.TemporaryDirectory() as tmp:
        world = _world(tmp)
        wm.WORLDS_DIR = Path(tmp)
        server, base = _serve()
        try:
            with sync_playwright() as pw:
                browser = _browser(pw)
                page = browser.new_page(viewport={"width": 1200, "height": 1600})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"{base}/places?level={LEVEL}")
                ui = Page(page, world)
                ui.eventually("the page loads its places", lambda: ui.dots("authored") == 1)
                # One page, in order: each test starts from the state the last one left.
                test_load_hides_names_and_grey_dots(ui)
                test_choose_place_then_move_rename_and_describe(ui)
                test_add_place_and_bad_input(ui)
                test_grey_place_turns_purple_with_info(ui)
                test_delete(ui)
                check("no JavaScript error on the page", errors == [])
                browser.close()
        finally:
            server.should_exit = True
            wm.WORLDS_DIR = old
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
