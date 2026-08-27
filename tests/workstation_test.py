#!/usr/bin/env python3
"""Headless integration checks for the PipeWire workstation shell."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chipforge_st import SynthCore, TrackerProject, generate_song
import chipforge_workstation as workstation_module
from chipforge_workstation import BUTTON_GLYPHS, VERSION, PipeWireOutput, Visualizer, Workstation

assert VERSION == "2.6.4-cherry-release"
icon_path = ROOT / "assets" / "chipforge-icon.png"
icon_bytes = icon_path.read_bytes()
assert icon_bytes[:8] == b"\x89PNG\r\n\x1a\n"
assert len(icon_bytes) > 100_000
assert {"play", "spark", "cycle", "disk", "download", "hammer", "eye", "grid", "expand"} <= set(BUTTON_GLYPHS)
assert all(pattern and all(set(row) <= {".", "#"} for row in pattern) for pattern in BUTTON_GLYPHS.values())
assert "BitmapImage" not in (ROOT / "chipforge_workstation.py").read_text()

class FakePhotoImage:
    def __init__(self, master, width, height):self.master=master;self.width=width;self.height=height;self.pixels=[]
    def put(self, color, location):self.pixels.append((color,location))
real_photo_image = workstation_module.tk.PhotoImage
workstation_module.tk.PhotoImage = FakePhotoImage
try:
    glyph_host = object.__new__(Workstation);glyph_host._button_icons=[]
    rendered_glyph = Workstation.glyph(glyph_host, object(), "play", "#ffffff")
    assert (rendered_glyph.width, rendered_glyph.height) == (10,10)
    assert rendered_glyph.pixels and glyph_host._button_icons == [rendered_glyph]
finally:
    workstation_module.tk.PhotoImage = real_photo_image

# Every keyboard branch has a permanent on-screen legend entry. Insert mode is
# explicitly contextual because its tracker note row overlaps command letters.
legend = " ".join((Workstation.GLOBAL_HOTKEYS, Workstation.MUSIC_HOTKEYS, Workstation.EDIT_HOTKEYS, Workstation.VISUAL_HOTKEYS))
for token in ("F1", "F6", "F11", "ESC", "SPACE", "TAB", "LEFT", "RIGHT", "UP", "DOWN", "PGUP", "PGDN",
              "G GENERATE", "M MUTATE", "A AUTO", "Y STYLE", "I INSERT", "W FORGE", "S SAVE", "E EXPORT",
              "2-6 OCTAVE", "Z S X D C V G B H N J M , NOTES", "BACKSPACE", "DELETE", "R MUTATE", "L LOOK",
              "E FX", "8 PIXEL", "H HUD", "F TAKEOVER"):
    assert token in legend, token

hotkeys = object.__new__(Workstation)
hotkeys.focus_side = "music"
hotkeys.insert = True
hotkey_calls = []
hotkeys.enter_note = lambda value: hotkey_calls.append(("note", value))
hotkeys.save_state = lambda: hotkey_calls.append(("save", None))
class NoteEvent: keysym = "s"; char = "s"
Workstation.key(hotkeys, NoteEvent())
assert hotkey_calls == [("note", "s")]

project = TrackerProject()
generate_song(project, 0, seed=12345)
core = SynthCore(project)
output = PipeWireOutput(core, no_audio=True)
output.start()
core.start(0)
time.sleep(0.05)
snapshot = output.snapshot()
rendered_frames = output.rendered_frames
output.close()

assert snapshot.shape == (512, 2)
assert snapshot.dtype.name == "float32"
assert abs(snapshot).max() > 0
# The audio pump must follow wall-clock time instead of rendering as fast as the
# CPU can feed the helper. Allow generous scheduler variance on CI.
assert 512 <= rendered_frames <= 44100 * .20
assert len(Visualizer.SCENES) == 10
assert Visualizer.SCENES[0] == "OSCOPE"
assert {"VAPOR SUN", "TAPE DECK", "RAIN GLASS"} <= set(Visualizer.SCENES)
assert len(Visualizer.LOOKS) == 6
assert {"VAPORWAVE", "LO-FI TAPE"} <= set(Visualizer.LOOKS)
assert len(Visualizer.FX) == 7
assert {"VHS", "RAIN"} <= set(Visualizer.FX)
assert Workstation.AUTO_LOOP_INTERVALS == (0, 1, 2, 4)
# The GUI timer consumes transport cycles once, applies one bounded stage per
# due interval, and reaches the immutable home theme on stage eight.
endless = object.__new__(Workstation)
endless.project = project.clone()
endless.theme_anchor = endless.project.clone()
endless.core = SynthCore(endless.project)
endless.core.playing = True
endless.auto_interval_index = 1
endless.auto_last_cycle = 0
endless.auto_variation = 0
class StatusRecorder:
    value = ""
    def set(self, value): self.value = value
endless.status = StatusRecorder()
for cycle in range(1, 9):
    endless.core.completed_cycles = cycle
    endless.maybe_auto_mutate()
    assert endless.auto_variation == cycle
assert endless.project.pattern == endless.theme_anchor.pattern
assert "PRIMARY THEME RETURNS" in endless.status.value
# Tape-era music presets automatically select their matching visual bank while
# the original styles and the default clean oscilloscope remain unchanged.
visual = object.__new__(Visualizer)
visual.scene = visual.look = visual.fx = 0
visual.title = "UNCHANGED"
visual.match_style("NEON NOIR")
assert (visual.scene, visual.look, visual.fx, visual.title) == (0, 0, 0, "UNCHANGED")
visual.match_style("MALL AFTER MIDNIGHT")
assert Visualizer.SCENES[visual.scene] == "VAPOR SUN"
assert Visualizer.LOOKS[visual.look] == "VAPORWAVE"
assert Visualizer.FX[visual.fx] == "VHS"
visual.match_style("RAINY WINDOW BEATS")
assert Visualizer.SCENES[visual.scene] == "RAIN GLASS"
assert Visualizer.LOOKS[visual.look] == "LO-FI TAPE"
assert Visualizer.FX[visual.fx] == "RAIN"
# Exercise every scene through a headless recording canvas. This catches bad
# coordinate expansion or a missing primitive without requiring an X server.
visual.phase = .75
visual.fps = 60.0
visual.pixel = False
visual.hud = True
visual.particles = []
visual.delete = lambda *_args, **_kwargs: None
visual.winfo_width = lambda: 960
visual.winfo_height = lambda: 540
primitive_count = [0]
def primitive(*_args, **_kwargs):
    primitive_count[0] += 1
    return primitive_count[0]
visual.create_line = primitive
visual.create_rectangle = primitive
visual.create_text = primitive
visual.create_oval = primitive
visual.create_arc = primitive
visual.create_polygon = primitive
visual.move = lambda *_args, **_kwargs: None
wave = snapshot.mean(axis=1)
for scene in range(len(Visualizer.SCENES)):
    visual.scene = scene
    visual.look = scene % len(Visualizer.LOOKS)
    visual.fx = 0
    visual.draw(wave, .12)
visual.scene = Visualizer.SCENES.index("TAPE DECK")
visual.look = Visualizer.LOOKS.index("VAPORWAVE")
visual.fx = Visualizer.FX.index("ALL FX")
visual.draw(wave, .12)
assert primitive_count[0] > 100
# Tk can report a 1- or 2-pixel canvas during its first layout pass.  The
# oscilloscope must still supply create_line() with a valid pair of points.
startup_points = Visualizer.points(None, 2, 2, snapshot[:, 0])
assert len(startup_points) == 4

# Deck takeover draws all four 16-row pages as a 2x2 surface and maps clicks
# back into the correct page/channel without needing a live display server.
class RecordingCanvas:
    def __init__(self): self.labels=[];self.primitives=0
    def winfo_width(self): return 1200
    def winfo_height(self): return 640
    def delete(self,*_args,**_kwargs): pass
    def create_text(self,*_args,**kwargs): self.primitives+=1;self.labels.append(kwargs.get("text",""));return self.primitives
    def create_line(self,*_args,**_kwargs): self.primitives+=1;return self.primitives
    def create_rectangle(self,*_args,**_kwargs): self.primitives+=1;return self.primitives
deck=object.__new__(Workstation);deck.tracker=RecordingCanvas();deck.view_mode="deck";deck.project=project.clone();deck.core=SynthCore(deck.project)
deck.row=0;deck.channel=0;deck.page=0
Workstation.draw_tracker(deck)
assert {"PAGE 1  //  00–0F","PAGE 2  //  10–1F","PAGE 3  //  20–2F","PAGE 4  //  30–3F"} <= set(deck.tracker.labels)
assert deck.tracker.primitives > 400
deck.set_focus=lambda _side:None
class Click: x=1100;y=590
Workstation.click_tracker(deck,Click())
assert deck.page==3 and 48 <= deck.row < 64 and 0 <= deck.channel < 6

# The takeover switch reparents the existing panes instead of opening a second
# Tk window, which was the fragile part of the previous fullscreen approach.
class FakeWidget:
    def __init__(self,name):self.name=name
    def __str__(self):return self.name
class UnhashablePaneId:
    __hash__=None
    def __init__(self,value):self.value=value
    def __str__(self):return self.value
class FakePane:
    def __init__(self,*items):self.items=list(items);self.sash=None
    def panes(self):return tuple(UnhashablePaneId(str(item)) for item in self.items)
    def forget(self,item):self.items.remove(item)
    def add(self,item,**_kwargs):self.items.append(item)
    def winfo_width(self):return 1200
    def sash_place(self,index,x,y):self.sash=(index,x,y)
class FakeControl:
    def __init__(self):self.value=""
    def configure(self,**kwargs):self.value=kwargs.get("text",self.value)
    def set(self,value):self.value=value
class FakeRoot:
    def after_idle(self,callback):callback()
switch=object.__new__(Workstation);switch.music=FakeWidget("music");switch.visual=FakeWidget("visual")
switch.pane=FakePane(switch.music,switch.visual);switch.view_btn=FakeControl();switch.status=FakeControl();switch.root=FakeRoot();switch.view_mode="split"
switch.set_focus=lambda side:setattr(switch,"focus_side",side)
Workstation.set_view(switch,"deck");assert switch.pane.items==[switch.music] and switch.focus_side=="music"
Workstation.set_view(switch,"visual");assert switch.pane.items==[switch.visual] and switch.focus_side=="visual"
Workstation.set_view(switch,"split");assert switch.pane.items==[switch.music,switch.visual] and switch.pane.sash==(0,600,1)
print("CHIPFORGE WORKSTATION integration test: PASS")
