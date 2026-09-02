#!/usr/bin/env python3
"""Headless integration checks for the PipeWire workstation shell."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chipforge_st import (SONG_PATHS, VOX_AUTOMATION, VOX_PAD_ACTIONS, VOX_WORDS, SynthCore,
                          TrackerProject, build_song_scene, generate_song, generate_vox_loop, parse_vox_words)
import chipforge_workstation as workstation_module
from chipforge_workstation import BUTTON_GLYPHS, VERSION, PipeWireOutput, Visualizer, Workstation

assert VERSION == "3.4.1-word-pads"
assert Workstation.VOX_WORD_BUTTON_WIDTH >= 120
assert Workstation.VOX_WORD_BUTTON_HEIGHT >= 30
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
legend = " ".join((Workstation.GLOBAL_HOTKEYS, Workstation.MUSIC_HOTKEYS, Workstation.EDIT_HOTKEYS,
                   Workstation.VISUAL_HOTKEYS, Workstation.SOUNDBOARD_HOTKEYS))
for token in ("F1", "F6", "F11", "ESC", "SPACE", "TAB", "LEFT", "RIGHT", "UP", "DOWN", "PGUP", "PGDN",
              "G GENERATE", "M MUTATE", "A EVOLVE", "Y ALL STYLES", "I INSERT", "W FORGE", "S SAVE", "E EXPORT",
              "P PATH", "N CUE NEXT", "O RETURN", "T LOOP SCENE",
              "7 SOUNDBOARD", "V STAB", "B DIVE", "1-8 FIRE PADS", "Q NEW LOOP", "R RANDOM WORDS", "C CLEAR",
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

# Live-set changes use a sample-domain master ramp instead of a hard cut.
transition_core = SynthCore(project.clone(), sample_rate=22050)
transition_core.start(0)
transition_core.set_output_gain(0.0)
transition_core.render(1024)
assert 0.0 < transition_core.output_gain < 1.0
transition_core.render(4096)
assert transition_core.output_gain < .2
transition_core.set_output_gain(1.0)
transition_core.render(4096)
assert transition_core.output_gain > .8
# The audio pump must follow wall-clock time instead of rendering as fast as the
# CPU can feed the helper. Allow generous scheduler variance on CI.
assert 512 <= rendered_frames <= 44100 * .20

# Track 7 is an independent four-bar soundboard. Manual pads and loop cells use
# the same transport clock; AUTO replaces patterns instead of adding chatter.
assert VOX_AUTOMATION == ("OFF", "LOOP", "AUTO")
assert len(VOX_PAD_ACTIONS) == 8 and "WUB" in VOX_PAD_ACTIONS
generated_loop = generate_vox_loop(project, 2)
assert len(generated_loop) == 16 and 1 <= sum(item != "---" for item in generated_loop) <= 2
vox_core = SynthCore(project.clone(), sample_rate=22050);vox_core.start(1)
vox_core.queue_vox("CALL", quantize="beat")
assert vox_core.vox_pending is not None and not vox_core.vox.active
for _ in range(3):vox_core.advance_row()
assert vox_core.current_row == 4 and vox_core.vox_pending is None and vox_core.vox.active
vox_audio = vox_core.render(4096)
assert abs(vox_audio).max() > .001 and len(vox_core.activity_levels()) == 7
loop_project=TrackerProject();loop_project.vox.automation="LOOP";loop_project.vox.loop=["---"]*16;loop_project.vox.loop[1]="WUB"
loop_core=SynthCore(loop_project,sample_rate=22050);loop_core.start(1)
for _ in range(3):loop_core.advance_row()
assert loop_core.current_row==4 and loop_core.vox.action=="WUB" and loop_core.vox.active
# CALL/ANSWER can seek the quietest lead beat inside the next bar instead of
# merely starting on time and talking over the melody.
gap_project = TrackerProject()
for row in range(4,12):gap_project.pattern[3][row].note=60
gap_core = SynthCore(gap_project);gap_core.start(1);gap_core.queue_vox("CALL",quantize="gap")
assert gap_core.vox_pending is not None and gap_core.vox_pending[3] == 12
turn_core = SynthCore(TrackerProject());turn_core.start(1);turn_core.queue_vox("HOOK",quantize="turn")
assert turn_core.vox_pending is not None and turn_core.vox_pending[2:] == ("turn",12)
late_turn = SynthCore(TrackerProject());late_turn.start(13);late_turn.queue_vox("HOOK",quantize="turn")
assert late_turn.vox_pending is not None and late_turn.vox_pending[3] == 28
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
# Beat editing is one-click obvious: a filled cell clears regardless of which
# pad is selected; the next click places the last touched pad.
edit_host=object.__new__(Workstation);edit_host.project=TrackerProject();edit_host.status=StatusRecorder()
edit_host.vox_selected_action="WUB";edit_host.project.vox.loop=["---"]*16;edit_host.project.vox.loop[3]="CALL"
edit_host.toggle_vox_step(3);assert edit_host.project.vox.loop[3]=="---" and "CLEARED" in edit_host.status.value
edit_host.toggle_vox_step(3);assert edit_host.project.vox.loop[3]=="WUB" and "WUB" in edit_host.status.value
edit_host.set_vox_automation("OFF");assert edit_host.project.vox.automation=="OFF" and "LIVE PADS ONLY" in edit_host.status.value
edit_host.set_vox_automation("AUTO");assert edit_host.project.vox.automation=="AUTO" and "SPARSE LOOP" in edit_host.status.value
assert VOX_WORDS[:3]==("OH","AH","OOH")
edit_host.project.vox.phrase="OH / AH";edit_host.cycle_vox_word(0)
assert edit_host.project.vox.phrase=="AH / AH"
edit_host.cycle_vox_word(2);assert parse_vox_words(edit_host.project.vox.phrase)==["AH","AH","HEY"]
edit_host.remove_vox_word();assert parse_vox_words(edit_host.project.vox.phrase)==["AH","AH"]
edit_host.vox_variation=0;edit_host.randomize_vox_words()
assert 1<=len(parse_vox_words(edit_host.project.vox.phrase))<=3 and "RANDOM VOCAL WORDS" in edit_host.status.value
for cycle in range(1, 9):
    endless.core.completed_cycles = cycle
    endless.maybe_auto_mutate()
    assert endless.auto_variation == cycle
assert endless.project.pattern == endless.theme_anchor.pattern
assert "ORIGINAL PERFORMANCE RETURNS" in endless.status.value

# Song Paths are four distinct, deterministic scenes and change the harmony
# without losing the original instruments or leaving the active scale.
assert tuple(SONG_PATHS) == ("LOOP", "LIFT", "JOURNEY", "BUILD", "VERSE/HOOK", "DREAM")
theme = project.clone()
scenes = [build_song_scene(theme, token) for token in SONG_PATHS["JOURNEY"]]
assert [scene.progression for scene in scenes][0] == theme.progression
assert scenes[-1].pattern == theme.pattern
assert len({scene.progression for scene in scenes}) >= 3
assert all(scene.instruments == theme.instruments for scene in scenes)

# Manual cues land on the next bar before that bar's first bass/chord trigger.
# Automatic Path movement remains locked to the four-bar cycle boundary.
path_host = object.__new__(Workstation)
path_host.project = theme.clone()
path_host.core = SynthCore(path_host.project)
path_host.song_path_anchor = theme.clone()
path_host.song_scenes = [(token, build_song_scene(theme, token)) for token in SONG_PATHS["LIFT"]]
path_host.song_scene_index = 0
path_host.song_path_queued = 2
path_host.song_path_event = None
path_host.path_hold = False
path_host.project.song_path_enabled = True
path_host.auto_variation = 3
path_host.auto_last_cycle = 0
path_host.core.cycle_callback = path_host._audio_cycle_boundary
path_host.core.bar_callback = path_host._audio_bar_boundary
path_host.core.start(15)
path_host.core.advance_row()
assert path_host.song_scene_index == 2 and path_host.core.current_row == 16
assert path_host.project.progression == path_host.song_scenes[2][1].progression
assert path_host.theme_anchor.pattern == path_host.project.pattern
assert path_host.auto_variation == 0
path_host.song_path_queued = None
path_host.core.current_row = 63
path_host.core.advance_row()
assert path_host.song_scene_index == 3 and path_host.core.current_row == 0
# AUTO only rewrites the sparse loop at a scene boundary. It must not fire an
# extra gesture outside the sixteen visible Track 7 cells.
auto_host = object.__new__(Workstation)
auto_host.project = theme.clone();auto_host.project.vox.automation="AUTO"
auto_host.core = SynthCore(auto_host.project);auto_host.core.playing=True
auto_host.song_scenes = [(token, build_song_scene(theme, token)) for token in SONG_PATHS["BUILD"]]
auto_host.song_scene_index=0;auto_host.song_path_event=None;auto_host.theme_anchor=theme.clone()
auto_host.auto_variation=0;auto_host.auto_last_cycle=0;auto_host.vox_variation=0
trigger_count=auto_host.core.vox.trigger_count
locked_words=auto_host.project.vox.phrase
auto_host._apply_song_scene_locked(1)
assert auto_host.core.vox.trigger_count==trigger_count
assert 1 <= sum(item!="---" for item in auto_host.project.vox.loop) <= 2
assert auto_host.project.vox.phrase==locked_words
# Enabling Evolve captures only the active performance variation; it must not
# rebuild or rewind the independent harmonic Song Map.
class ButtonRecorder:
    def __init__(self): self.values = {}
    def configure(self, **values): self.values.update(values)
path_host.auto_interval_index = 0
path_host.auto_btn = ButtonRecorder()
path_host.status = StatusRecorder()
scene_bank = path_host.song_scenes
path_host.cycle_auto_mutate()
assert path_host.song_scene_index == 3 and path_host.song_scenes is scene_bank
assert path_host.auto_interval_index == 1
path_host._queue_scene(0)
assert path_host.song_path_queued == 0 and "NEXT BAR" in path_host.status.value
path_host._queue_scene(0)
assert path_host.song_path_queued is None and "CANCELED" in path_host.status.value
class MapCanvas:
    def __init__(self): self.items=[]
    def delete(self, *_args): self.items=[]
    def winfo_width(self): return 900
    def winfo_height(self): return 72
    def create_rectangle(self, *args, **kwargs): self.items.append(("rectangle",args,kwargs))
    def create_text(self, *args, **kwargs): self.items.append(("text",args,kwargs))
path_host.path_btn = ButtonRecorder();path_host.path_hold_btn = ButtonRecorder()
path_host.path_next_btn = ButtonRecorder();path_host.path_home_btn = ButtonRecorder();path_host.path_map = MapCanvas()
path_host.update_path_controls()
assert path_host.path_home_btn.values["state"] == "disabled"
assert sum(item[0] == "rectangle" for item in path_host.path_map.items) >= 4
assert any(item[0] == "text" and item[2].get("text") == "PLAYING" for item in path_host.path_map.items)
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
switch=object.__new__(Workstation);switch.music=FakeWidget("music");switch.visual=FakeWidget("visual");switch.soundboard=FakeWidget("soundboard")
switch.pane=FakePane(switch.music,switch.visual);switch.view_btn=FakeControl();switch.status=FakeControl();switch.root=FakeRoot();switch.view_mode="split"
switch.set_focus=lambda side:setattr(switch,"focus_side",side)
Workstation.set_view(switch,"deck");assert switch.pane.items==[switch.music] and switch.focus_side=="music"
Workstation.set_view(switch,"visual");assert switch.pane.items==[switch.visual] and switch.focus_side=="visual"
Workstation.set_view(switch,"soundboard");assert switch.pane.items==[switch.soundboard] and switch.focus_side=="soundboard"
Workstation.set_view(switch,"split");assert switch.pane.items==[switch.music,switch.visual] and switch.pane.sash==(0,600,1)
print("CHIPFORGE WORKSTATION integration test: PASS")
