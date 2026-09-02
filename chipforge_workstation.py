#!/usr/bin/env python3
"""CHIPFORGE WORKSTATION — integrated tracker, PipeWire synth and visualizer."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import random
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from chipforge_st import (
    CHANNEL_COUNT, CHANNEL_NAMES, DRUM_CHANNELS, LOFI_STYLE_NAMES, NOTE_KEYS, NOTE_OFFSETS,
    SONG_PATHS, SONG_PATH_SCENE_NAMES, STYLES,
    VAPORWAVE_STYLE_NAMES, VOX_AUTOMATION, VOX_MODES, VOX_PAD_ACTIONS, VOX_PAD_LABELS, VOX_VOICES, VOX_WORDS, WAVEFORMS, Step,
    SynthCore, TrackerProject, clamp, export_project, generate_song,
    build_song_scene, generate_vox_loop, generate_vox_phrase, midi_name, mutate_song, parse_vox_words, render_project, theme_variation, write_wav,
)

APP = "CHIPFORGE WORKSTATION"
VERSION = "3.4.1-word-pads"
MONO = "DejaVu Sans Mono"
BG, PANEL, GRID = "#05070a", "#0b1118", "#173044"
CYAN, PINK, LIME, AMBER, WHITE, MUTED = "#3df6ff", "#ff3cac", "#8cff5a", "#ffc857", "#edfaff", "#68869a"

# Tiny monochrome pixel glyphs are drawn into native Tk PhotoImages. They avoid
# emoji, platform-font substitutions and XBM parser differences, so every
# packaged build gets identical button icons on Linux, Windows and macOS.
BUTTON_GLYPHS: dict[str, tuple[str, ...]] = {
    "play": ("..........", "..#.......", "..###.....", "..#####...", "..#######.", "..#######.", "..#####...", "..###.....", "..#.......", ".........."),
    "spark": ("....#.....", "....#.....", ".#..#..#..", "..#.##.#..", "...####...", "#########.", "...####...", "..#.##.#..", ".#..#..#..", "....#....."),
    "cycle": ("...####...", ".##....##.", "##........", "##.....##.", ".......###", "###.......", ".##.....##", "........##", ".##....##.", "...####..."),
    "diamond": ("....##....", "...####...", "..######..", ".########.", "##########", "##########", ".########.", "..######..", "...####...", "....##...."),
    "disk": ("##########", "##.....###", "##.###.###", "##.....###", "##########", "##......##", "##.####.##", "##.####.##", "##......##", "##########"),
    "folder": ("..........", ".####.....", ".######...", "#########.", "##......##", "##......##", "##......##", "##......##", ".########.", ".........."),
    "download": ("....##....", "....##....", "....##....", ".##.##.##.", "..######..", "...####...", "....##....", "..........", ".########.", ".########."),
    "hammer": ("..#####...", "..#####...", "....##....", "....###...", "...###....", "..###.....", ".###......", "###.......", "##........", ".........."),
    "chip": ("..#.#.#...", ".########.", "##......##", ".#.####.#.", "##.####.##", ".#.####.#.", "##......##", ".########.", "..#.#.#...", ".........."),
    "clock": ("...####...", ".##....##.", "##..#...##", "##..#...##", "##..####.#", "##......##", "##......##", ".##....##.", "...####...", ".........."),
    "lanes": (".##.##.##.", ".##.##.##.", ".##.##.##.", ".##.##.##.", ".##.##.##.", ".##.##.##.", ".##.##.##.", ".##.##.##.", ".##.##.##.", ".........."),
    "wave": ("..........", "..........", "......##..", ".##...##..", ".###.##...", "...###....", "...##.###.", "..##...##.", "..........", ".........."),
    "cursor": ("#.........", "##........", "###.......", "####......", "#####.....", "###.......", "#.##......", "...##.....", "..........", ".........."),
    "left": ("....##....", "...##.....", "..##......", ".########.", "##########", ".########.", "..##......", "...##.....", "....##....", ".........."),
    "right": ("....##....", ".....##...", "......##..", ".########.", "##########", ".########.", "......##..", ".....##...", "....##....", ".........."),
    "clear": ("##......##", ".##....##.", "..##..##..", "...####...", "....##....", "...####...", "..##..##..", ".##....##.", "##......##", ".........."),
    "speaker": ("..........", "....##....", "..####....", "######.##.", "######..##", "######..##", "######.##.", "..####....", "....##....", ".........."),
    "eye": ("..........", "...####...", ".##....##.", "##..##..##", "##.####.##", "##.####.##", "##..##..##", ".##....##.", "...####...", ".........."),
    "grid": ("###..###..", "###..###..", "###..###..", "..........", "###..###..", "###..###..", "###..###..", "..........", "..........", ".........."),
    "screen": ("##########", "##......##", "##......##", "##.####.##", "##.#..#.##", "##.####.##", "##......##", "##########", "...####...", ".........."),
    "expand": ("###....###", "##......##", "#.#....#.#", "..........", "..........", "..........", "..........", "#.#....#.#", "##......##", "###....###"),
}


def user_data_root() -> Path:
    """Stable writable storage; Steam may replace every file in its depot."""
    base = Path.home() / ".local" / "share"
    if value := __import__("os").environ.get("XDG_DATA_HOME"):
        base = Path(value).expanduser()
    root = base / "chipforge"
    root.mkdir(parents=True, exist_ok=True)
    return root


class PipeWireOutput:
    """Writes the synth's signed PCM directly to a PipeWire stream via pw-cat."""
    def __init__(self, core: SynthCore, no_audio: bool = False):
        self.core, self.no_audio = core, no_audio
        self.process: subprocess.Popen[bytes] | None = None
        self.running = False
        self.thread: threading.Thread | None = None
        self.description = "NO AUDIO" if no_audio else "PIPEWIRE"
        self.error = ""
        self.latest = np.zeros((1024, 2), dtype=np.float32)
        self.rendered_frames = 0
        self.lock = threading.Lock()

    def start(self) -> None:
        if self.running:
            return
        if not self.no_audio:
            bundled = Path(__file__).resolve().parent / "chipforge-pw-sink"
            binary = str(bundled) if bundled.is_file() else shutil.which("pw-cat")
            if not binary:
                raise RuntimeError("PipeWire output bridge was not found. Reinstall CHIPFORGE or use --no-audio.")
            if Path(binary).name == "chipforge-pw-sink":
                command = [binary, str(self.core.sample_rate), "2"]
                self.description = "PIPEWIRE NATIVE :: BUNDLED BRIDGE"
            else:
                command = [binary, "--playback", "--raw", "--rate", str(self.core.sample_rate),
                           "--channels", "2", "--format", "s16", "-"]
                self.description = "PIPEWIRE NATIVE :: pw-cat"
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.running = True
        self.thread = threading.Thread(target=self._pump, name="chipforge-pipewire", daemon=True)
        self.thread.start()

    def _pump(self) -> None:
        frames = 512
        deadline = time.perf_counter()
        while self.running:
            try:
                audio = self.core.render(frames)
                self.rendered_frames += frames
            except Exception as exc:
                self.error = f"Synth stopped: {exc}"
                self.running = False
                break
            with self.lock:
                self.latest = audio.copy()
            if self.process and self.process.stdin:
                try:
                    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2", copy=False)
                    self.process.stdin.write(pcm.tobytes())
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError, ValueError) as exc:
                    # close() can shut stdin between the checks above and the
                    # write.  That is a normal shutdown race, not an audio
                    # failure worth reporting to the UI.
                    if self.running:
                        self.error = str(exc)
                    self.running = False
                    break
            # The synth owns musical time. PipeWire backpressure is a safety net,
            # but wall-clock pacing here prevents any helper implementation from
            # making transport, visuals or note envelopes race ahead.
            deadline += frames / self.core.sample_rate
            delay = deadline - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -.25:
                deadline = time.perf_counter()

    def snapshot(self) -> np.ndarray:
        with self.lock:
            return self.latest.copy()

    def close(self) -> None:
        self.running = False
        if self.process:
            if self.process.stdin:
                try: self.process.stdin.close()
                except OSError: pass
            self.process.terminate()
            try: self.process.wait(timeout=1)
            except subprocess.TimeoutExpired: self.process.kill()
            self.process = None


class Visualizer(tk.Canvas):
    SCENES = ("OSCOPE", "CATHEDRAL", "TUNNEL", "SIGNAL", "WAVEFORM", "SPECTRUM", "RIPPLES",
              "VAPOR SUN", "TAPE DECK", "RAIN GLASS")
    LOOKS = ("CLEAN", "VICE CITY", "PSYCHEDELIC", "VISUAL TRAILER", "VAPORWAVE", "LO-FI TAPE")
    FX = ("NONE", "SMOKE", "RIPPLES", "LIGHTING", "ALL FX", "VHS", "RAIN")
    WORDS_A = ("NEON", "MIDNIGHT", "TURBO", "COSMIC", "PLASMA", "VELVET", "LASER", "GHOST", "VHS", "DUSTY")
    WORDS_B = ("FLAMINGO", "CATHEDRAL", "ARCADE", "SATELLITE", "HIGHWAY", "RITUAL", "CASSETTE", "PLAZA", "WINDOW")
    WORDS_C = ("AFTER DARK", "TRANSMISSION", "DREAM MACHINE", "FEVER", "SIGNAL", "FOREVER", "SIDE A", "MEMORY", "IN THE RAIN")

    def __init__(self, master: tk.Misc, audio: PipeWireOutput):
        super().__init__(master, bg=BG, highlightthickness=1, highlightbackground=GRID)
        self.audio = audio
        self.scene = self.look = self.fx = 0
        self.pixel = False
        self.hud = True
        self.title = self.make_name()
        self.phase = 0.0
        self.last = time.perf_counter()
        self.fps, self.frames, self.fps_clock = 0.0, 0, self.last
        self.particles: list[list[float]] = []
        self.tick_job: str | None = self.after(16, self.tick)

    def destroy(self) -> None:
        if self.tick_job is not None:
            try:self.after_cancel(self.tick_job)
            except tk.TclError:pass
            self.tick_job=None
        super().destroy()

    def make_name(self) -> str:
        return f"{random.choice(self.WORDS_A)} {random.choice(self.WORDS_B)} {random.choice(self.WORDS_C)}"

    def cycle_scene(self, delta: int = 1) -> None:
        self.scene = (self.scene + delta) % len(self.SCENES); self.title = self.make_name()
    def cycle_look(self) -> None: self.look = (self.look + 1) % len(self.LOOKS)
    def cycle_fx(self) -> None: self.fx = (self.fx + 1) % len(self.FX)
    def mutate(self) -> None:
        self.scene = random.randrange(len(self.SCENES)); self.look = random.randrange(len(self.LOOKS))
        self.fx = random.randrange(len(self.FX)); self.title = self.make_name()

    def match_style(self, style: str) -> None:
        """Give new tape-era presets a matching stage without touching others."""
        if style in VAPORWAVE_STYLE_NAMES:
            self.scene = self.SCENES.index("VAPOR SUN")
            self.look = self.LOOKS.index("VAPORWAVE")
            self.fx = self.FX.index("VHS")
            self.title = f"{style} // VISUAL MEMORY"
        elif style in LOFI_STYLE_NAMES:
            self.scene = self.SCENES.index("RAIN GLASS")
            self.look = self.LOOKS.index("LO-FI TAPE")
            self.fx = self.FX.index("RAIN")
            self.title = f"{style} // SIDE A"

    def palette(self, energy: float) -> tuple[str, str, str]:
        tables = ((CYAN, PINK, LIME), ("#00e5ff", "#ff2a91", "#ffd166"),
                  ("#ffea00", "#ff00d4", "#00ff9d"), ("#f7d08a", "#df6c4f", "#65d7d1"),
                  ("#7cf7ff", "#ff71ce", "#b967ff"), ("#d7bd96", "#c77d6b", "#82a58d"))
        return tables[self.look]

    def tick(self) -> None:
        now = time.perf_counter(); dt = min(.05, now - self.last); self.last = now
        self.phase += dt
        data = self.audio.snapshot().mean(axis=1)
        energy = float(np.sqrt(np.mean(data * data))) if data.size else 0.0
        self.draw(data, energy)
        self.frames += 1
        if now - self.fps_clock >= .5:
            self.fps = self.frames / (now - self.fps_clock); self.frames = 0; self.fps_clock = now
        self.tick_job=self.after(1, self.tick)

    def draw(self, wave: np.ndarray, energy: float) -> None:
        self.delete("all"); w, h = max(2, self.winfo_width()), max(2, self.winfo_height())
        c1, c2, c3 = self.palette(energy); bass = min(1.0, energy * 7)
        if self.look == 1:
            self.create_rectangle(0, 0, w, h, fill="#08051b", outline="")
            for y in range(h // 2, h, 18): self.create_line(0, y, w, y, fill="#26154a")
        elif self.look == 3:
            self.create_rectangle(0, 0, w, h, fill="#090c0d", outline="")
            self.create_rectangle(0, 0, w, h*.13, fill="#000", outline=""); self.create_rectangle(0, h*.87, w, h, fill="#000", outline="")
        elif self.look == 4:
            bands = ("#171238", "#251850", "#442269", "#743070", "#b64b79", "#ef7f8d")
            for index, color in enumerate(bands):
                self.create_rectangle(0, index*h/len(bands), w, (index+1)*h/len(bands)+1, fill=color, outline="")
            self.create_rectangle(0, h*.62, w, h, fill="#09091b", outline="")
        elif self.look == 5:
            self.create_rectangle(0, 0, w, h, fill="#100e0c", outline="")
            for y in range(0, h, 12): self.create_line(0, y, w, y, fill="#1d1914")
        scene = self.SCENES[self.scene]
        if scene == "OSCOPE": self.oscope(w, h, wave)
        elif scene == "WAVEFORM": self.waveform(w, h, wave, c1, c2)
        elif scene == "SPECTRUM": self.spectrum(w, h, wave, c1, c2)
        elif scene == "TUNNEL": self.tunnel(w, h, bass, c1, c2)
        elif scene == "CATHEDRAL": self.cathedral(w, h, wave, c1, c2)
        elif scene == "RIPPLES": self.ripples(w, h, bass, c1, c2)
        elif scene == "VAPOR SUN": self.vapor_sun(w, h, wave, bass, c1, c2, c3)
        elif scene == "TAPE DECK": self.tape_deck(w, h, wave, bass, c1, c2)
        elif scene == "RAIN GLASS": self.rain_glass(w, h, wave, bass, c1, c2)
        else: self.signal(w, h, wave, c1, c2, c3)
        if self.fx in (1, 4): self.smoke(w, h, energy, c2)
        if self.fx in (2, 4): self.ripples(w, h, bass, c3, c1, faint=True)
        if self.fx in (3, 4): self.lighting(w, h, bass, c1, c2)
        if self.fx in (4, 5): self.vhs(w, h, c1, c2)
        if self.fx in (4, 6): self.rain(w, h, c1)
        if self.pixel:
            step = max(4, w // 160)
            for x in range(0, w, step): self.create_line(x, 0, x, h, fill="#05070a", stipple="gray75")
        if self.hud:
            title = "LIVE PCM OSCILLOSCOPE" if scene == "OSCOPE" else self.title
            self.create_text(16, 15, anchor="nw", text=title, fill=WHITE, font=(MONO, 13, "bold"))
            self.create_text(16, 38, anchor="nw", text=f"{scene}  /  {self.LOOKS[self.look]}  /  {self.FX[self.fx]}", fill=c1, font=(MONO, 9))
            self.create_text(w-14, 15, anchor="ne", text=f"{self.fps:5.1f} FPS", fill=LIME, font=(MONO, 10, "bold"))

    def points(self, w: int, h: int, wave: np.ndarray, scale=.36) -> list[float]:
        if wave.size < 2: return [0, h/2, w, h/2]
        # A newly mapped Tk canvas can briefly report width=1 before geometry
        # propagation.  Always emit at least two points: create_line() raises
        # IndexError when its expanded coordinate tuple is empty.
        sample_count = min(max(2, w//3), wave.size)
        idx = np.linspace(0, wave.size-1, sample_count).astype(int)
        out=[]
        for n, v in enumerate(wave[idx]): out.extend((n*w/max(1,len(idx)-1), h*.5-float(v)*h*scale))
        return out
    def waveform(self,w,h,wave,c1,c2):
        self.create_line(*self.points(w,h,wave), fill=c1, width=3, smooth=True)
        self.create_line(*self.points(w,h,np.roll(wave,23),.22), fill=c2, width=1, smooth=True)
    def oscope(self,w,h,wave):
        self.create_rectangle(0,0,w,h,fill="#020708",outline="")
        for division in range(1,10):
            x=division*w/10; self.create_line(x,0,x,h,fill="#0c2529")
        for division in range(1,8):
            y=division*h/8; self.create_line(0,y,w,y,fill="#0c2529")
        self.create_line(0,h/2,w,h/2,fill="#24545a",width=1)
        if wave.size < 4:return
        signal=wave.astype(np.float64)-float(np.mean(wave))
        crossings=np.flatnonzero((signal[:-1] <= 0) & (signal[1:] > 0))
        start=int(crossings[0]) if crossings.size else 0
        span=min(len(signal)-start,max(256,min(2048,w*2)))
        if span < 64:start=0;span=len(signal)
        signal=signal[start:start+span]
        peak=max(.0001,float(np.max(np.abs(signal))))
        rms=float(np.sqrt(np.mean(signal*signal)))
        gain=min(4.0,.82/peak)
        trace=np.clip(signal*gain,-1,1)
        self.create_line(*self.points(w,h,trace,.43),fill="#69f6ff",width=2,smooth=False)
        self.create_text(w-14,h-14,anchor="se",text=f"DIRECT MASTER PCM   PEAK {peak:.3f}   RMS {rms:.3f}   GAIN {gain:.2f}x",fill="#57aeb5",font=(MONO,8))
    def spectrum(self,w,h,wave,c1,c2):
        if wave.size < 8:return
        bins=np.abs(np.fft.rfft(wave*np.hanning(len(wave))))[:64]; bins/=max(.001,float(bins.max()))
        bw=w/len(bins)
        for i,v in enumerate(bins):
            top=h-float(v)*h*.78; self.create_rectangle(i*bw+1,top,(i+1)*bw-2,h,fill=c1 if i%3 else c2,outline="")
    def tunnel(self,w,h,bass,c1,c2):
        cx,cy=w/2,h/2
        for i in range(18):
            p=((i/18+self.phase*.24)%1); r=(p*p)*max(w,h)*.72+8*bass
            self.create_oval(cx-r,cy-r*.58,cx+r,cy+r*.58,outline=c1 if i%2 else c2,width=2)
    def cathedral(self,w,h,wave,c1,c2):
        vals=np.abs(wave[::max(1,len(wave)//40)]) if wave.size else np.zeros(40)
        for i,v in enumerate(vals[:40]):
            x=(i+.5)*w/40; bh=h*(.12+float(v)*.7); self.create_line(x,h*.82,x,h*.82-bh,fill=c1 if i%2 else c2,width=max(2,w//120))
            self.create_line(w-x,h*.82,w-x,h*.82-bh,fill=c1 if i%2 else c2,width=max(2,w//120))
        self.create_arc(w*.28,h*.16,w*.72,h*.82,start=0,extent=180,style="arc",outline=c2,width=3)
    def signal(self,w,h,wave,c1,c2,c3):
        self.waveform(w,h,wave,c1,c2); self.spectrum(w,int(h*.92),wave,c3,c2)
        self.create_oval(w*.44,h*.36,w*.56,h*.64,outline=c2,width=3)
    def ripples(self,w,h,bass,c1,c2,faint=False):
        cx=w*(.5+math.sin(self.phase*.37)*.12); cy=h*(.5+math.cos(self.phase*.29)*.1)
        for i in range(10):
            r=((i/10+self.phase*.35)%1)*min(w,h)*.65
            self.create_oval(cx-r,cy-r,cx+r,cy+r,outline=c1 if i%2 else c2,width=1 if faint else 3)
    def smoke(self,w,h,energy,color):
        if energy>.015 and len(self.particles)<55:
            self.particles.append([random.random()*w,h+20,random.uniform(-.3,.3),random.uniform(-1.5,-.4),random.uniform(12,40)])
        alive=[]
        for p in self.particles:
            p[0]+=p[2];p[1]+=p[3];p[4]*=.996
            if p[1]>-50 and p[4]>5:
                alive.append(p); self.create_oval(p[0]-p[4],p[1]-p[4],p[0]+p[4],p[1]+p[4],outline=color,stipple="gray75")
        self.particles=alive
    def lighting(self,w,h,bass,c1,c2):
        spread=w*(.08+.18*bass)
        self.create_polygon(w/2,h*.4,w/2-spread,h,w/2+spread,h,fill=c1,outline="",stipple="gray50")
        self.create_polygon(w*.2,0,w*.1,h,w*.35,h,fill=c2,outline="",stipple="gray75")

    def vapor_sun(self,w,h,wave,bass,c1,c2,c3):
        horizon=h*.58; radius=min(w,h)*(.12+.025*bass); cx=w*.5
        self.create_oval(cx-radius,horizon-radius*1.65,cx+radius,horizon+radius*.35,fill="#ff9b71",outline=c2,width=3)
        for stripe in range(6):
            y=horizon-radius*1.25+stripe*radius*.28
            self.create_line(cx-radius,y,cx+radius,y,fill="#5b286d",width=max(2,int(radius*.07)))
        self.create_line(0,horizon,w,horizon,fill=c1,width=2)
        for division in range(-9,10):
            self.create_line(cx+division*w*.045,horizon,cx+division*w*.14,h,fill="#59316f")
        for row in range(1,9):
            p=(row/9)**1.75; y=horizon+(h-horizon)*p
            self.create_line(0,y,w,y,fill="#59316f")
        if wave.size >= 2:
            pts=self.points(w,int(horizon*1.12),wave,.10)
            self.create_line(*pts,fill=c3,width=2,smooth=True)

    def tape_deck(self,w,h,wave,bass,c1,c2):
        left,top,right,bottom=w*.13,h*.22,w*.87,h*.78
        self.create_rectangle(left,top,right,bottom,fill="#171613",outline=c1,width=3)
        self.create_rectangle(w*.22,h*.31,w*.78,h*.65,fill="#29251f",outline="#8b745a",width=2)
        for center_x,direction in ((w*.35,1),(w*.65,-1)):
            radius=min(w,h)*(.085+.01*bass)
            self.create_oval(center_x-radius,h*.48-radius,center_x+radius,h*.48+radius,outline=c2,width=4)
            angle=self.phase*(2.1+1.8*bass)*direction
            for spoke in range(3):
                a=angle+spoke*math.tau/3
                self.create_line(center_x,h*.48,center_x+math.cos(a)*radius*.76,h*.48+math.sin(a)*radius*.76,fill=c1,width=3)
        self.create_polygon(w*.38,h*.62,w*.62,h*.62,w*.69,h*.72,w*.31,h*.72,fill="#0d0d0c",outline=c2,width=2)
        if wave.size >= 2:
            trace=self.create_line(*self.points(int(w*.46),int(h*.19),wave,.28),fill=c1,width=1,smooth=True)
            self.move(trace,w*.27,h*.37)
        self.create_text(w*.5,h*.27,text="CHIPFORGE // TYPE II",fill=c1,font=(MONO,10,"bold"))

    def rain_glass(self,w,h,wave,bass,c1,c2):
        horizon=h*.68
        for building in range(12):
            x=building*w/12; bw=w/10
            height=h*(.12+.22*((building*7)%11)/10)
            self.create_rectangle(x,horizon-height,x+bw,horizon,fill="#171817",outline="#282923")
            for window in range(3):
                wx=x+bw*(.18+window*.27)
                self.create_rectangle(wx,horizon-height*.78,wx+bw*.10,horizon-height*.68,fill=c2 if (building+window)%3==0 else "#504633",outline="")
        self.create_line(0,horizon,w,horizon,fill=c2,width=2)
        if wave.size >= 2:
            self.create_line(*self.points(w,h,wave,.24),fill=c1,width=2,smooth=True)
        glow=min(w,h)*(.05+.04*bass)
        self.create_oval(w*.78-glow,h*.24-glow,w*.78+glow,h*.24+glow,fill="#d3a66f",outline="",stipple="gray50")

    def vhs(self,w,h,c1,c2):
        offset=int((math.sin(self.phase*2.4)+1)*h*.38)
        for y in range(3,h,8): self.create_line(0,y,w,y,fill="#09090c",stipple="gray75")
        self.create_rectangle(0,offset,w,offset+max(2,h*.012),fill=c1,outline="",stipple="gray50")
        for index in range(4):
            y=(index*137+self.phase*53)%max(1,h)
            x=w*(.08+.16*index)
            self.create_rectangle(x,y,min(w,x+w*(.08+.03*index)),y+2,fill=c2,outline="")

    def rain(self,w,h,color):
        for index in range(42):
            x=(index*83.0+math.sin(index*1.7)*47.0)%max(1,w)
            y=(index*127.0+self.phase*(180+index%5*23))%max(1,h+60)-30
            length=8+(index%6)*4
            self.create_line(x,y,x-2,y+length,fill=color,width=1,stipple="gray50")


class Workstation:
    AUTO_LOOP_INTERVALS = (0, 1, 2, 4)  # off, then every 4/8/16 bars
    # Tk interprets width/height as pixels when a button also has an image.
    # Keep these large enough for the slot number, glyph and full word.
    VOX_WORD_BUTTON_WIDTH = 132
    VOX_WORD_BUTTON_HEIGHT = 32
    GLOBAL_HOTKEYS = "GLOBAL  F1 HELP  |  F6 FOCUS / TAKEOVER SWAP  |  F11 FULLSCREEN  |  ESC BACK"
    MUSIC_HOTKEYS = (
        "MUSIC COMMANDS (INSERT OFF)  SPACE PLAY  |  G GENERATE  M MUTATE  Y ALL STYLES  A EVOLVE  F FLOW  "
        "P PATH  N CUE NEXT  O RETURN  T LOOP SCENE  |  7 SOUNDBOARD  V STAB  B DIVE  |  "
        "I INSERT  W FORGE  S SAVE  E EXPORT  H HELP"
    )
    EDIT_HOTKEYS = (
        "EDIT  TAB / LEFT / RIGHT LANE  |  UP / DOWN ROW  |  PGUP / PGDN OR [ / ] PAGE  |  "
        "INSERT ON: 2-6 OCTAVE  Z S X D C V G B H N J M , NOTES  BACKSPACE / DELETE ERASE  I EXIT"
    )
    VISUAL_HOTKEYS = "VISUAL  LEFT / RIGHT SCENE  |  R MUTATE  L LOOK  E FX  8 PIXEL  H HUD  F TAKEOVER"
    SOUNDBOARD_HOTKEYS = "TRACK 7  1-8 FIRE PADS  |  Q NEW LOOP  R RANDOM WORDS  C CLEAR  A MODE  V VOICE  M BODY  ESC BACK"

    def __init__(self, args: argparse.Namespace):
        self.args=args; self.root=tk.Tk(); self.root.tk.call("tk", "scaling", 1.0); self.root.title(f"{APP} {VERSION}"); self.root.configure(bg=BG)
        self.root.geometry(args.geometry); self.root.minsize(980,620)
        self.app_icon:tk.PhotoImage|None=None;self._button_icons:list[tk.PhotoImage]=[]
        try:
            self.app_icon=tk.PhotoImage(master=self.root,file=str(Path(__file__).resolve().parent/"assets"/"chipforge-icon.png"))
            self.root.iconphoto(True,self.app_icon)
        except (OSError,tk.TclError):
            self.app_icon=None
        self.project=TrackerProject.load(args.project) if args.project.exists() else TrackerProject()
        self.project_path=args.project
        self.style_index=next((i for i,s in enumerate(STYLES) if s["name"]==self.project.style),0)
        if not args.project.exists(): generate_song(self.project,self.style_index)
        self.core=SynthCore(self.project,args.sample_rate); self.audio=PipeWireOutput(self.core,args.no_audio)
        self.row=0; self.channel=0; self.page=0; self.octave=3; self.insert=False; self.focus_side="music"
        self.theme_anchor=self.project.clone();self.song_path_anchor=self.project.clone();self.song_scenes=[]
        self.song_scene_index=0;self.song_path_queued=None;self.song_path_event=None
        self.path_hold=not self.project.song_path_enabled
        self.auto_interval_index=0;self.auto_last_cycle=0;self.auto_variation=0
        self.vox_variation=0;self.vox_selected_action="WUB"
        self._rebuild_song_path();self.core.cycle_callback=self._audio_cycle_boundary;self.core.bar_callback=self._audio_bar_boundary
        self.view_mode="split";self.flow_window:tk.Toplevel|None=None;self.path_window:tk.Toplevel|None=None;self.style_window:tk.Toplevel|None=None;self.transition_busy=False
        self.state_slot=tk.IntVar(value=0)
        self.status=tk.StringVar(value="READY"); self.bpm=tk.IntVar(value=self.project.bpm); self.swing=tk.DoubleVar(value=self.project.swing)
        self.randomness=tk.DoubleVar(value=self.project.randomness*100);self.harmonic_motion=tk.DoubleVar(value=self.project.harmonic_motion*100)
        self.blend_target=tk.StringVar(value=self.project.blend_style or "NO BLEND");self.blend_amount=tk.DoubleVar(value=self.project.blend_amount*100)
        self.track_count=tk.IntVar(value=self.project.track_count)
        self.build(); self.bind(); self.vis.match_style(self.project.style); self.audio.start(); self.core.start(0);self.play_btn.configure(text="STOP")
        self.refresh(); self.root.protocol("WM_DELETE_WINDOW",self.close)

    def apply_window_icon(self,window):
        if self.app_icon is not None:
            try:window.iconphoto(True,self.app_icon)
            except tk.TclError:pass
    def glyph(self,parent,name,color):
        pattern=BUTTON_GLYPHS[name];width=max(len(row) for row in pattern);height=len(pattern)
        image=tk.PhotoImage(master=parent,width=width,height=height)
        for y,row in enumerate(pattern):
            for x,pixel in enumerate(row):
                if pixel=="#":image.put(color,(x,y))
        self._button_icons.append(image);return image
    def button(self,parent,text,command,color=CYAN,glyph="spark",**kw):
        image=self.glyph(parent,glyph,color)
        options={"bg":PANEL,"fg":color,"activebackground":color,"activeforeground":BG,
                 "relief":"flat","bd":0,"padx":8,"pady":5,"font":(MONO,9,"bold")}
        options.update(kw)
        return tk.Button(parent,text=text,image=image,compound="left",command=command,**options)
    def build(self):
        top=tk.Frame(self.root,bg=BG);top.pack(fill="x",padx=8,pady=(8,4))
        tk.Label(top,text="CHIPFORGE",fg=CYAN,bg=BG,font=(MONO,17,"bold")).pack(side="left")
        tk.Label(top,text=" // PIPEWIRE VISUAL WORKSTATION",fg=PINK,bg=BG,font=(MONO,12,"bold")).pack(side="left")
        self.view_btn=self.button(top,"VIEW SPLIT",self.cycle_view,AMBER,"grid");self.view_btn.pack(side="right",padx=(8,0))
        tk.Label(top,textvariable=self.status,fg=LIME,bg=BG,font=(MONO,9)).pack(side="right")
        self.pane=tk.PanedWindow(self.root,orient="horizontal",bg=GRID,sashwidth=6,handlesize=8,showhandle=True)
        self.pane.pack(fill="both",expand=True,padx=8,pady=4)
        self.music=tk.Frame(self.pane,bg=PANEL,highlightbackground=GRID,highlightthickness=1)
        self.visual=tk.Frame(self.pane,bg=PANEL,highlightbackground=GRID,highlightthickness=1)
        self.soundboard=tk.Frame(self.pane,bg="#100912",highlightbackground=PINK,highlightthickness=1)
        self.pane.add(self.music,stretch="always",minsize=430); self.pane.add(self.visual,stretch="always",minsize=430)
        self.build_music();self.build_visual();self.build_soundboard()
        foot=tk.Frame(self.root,bg=BG,highlightbackground=GRID,highlightthickness=1);foot.pack(fill="x",padx=8,pady=(4,8))
        legend=tk.Frame(foot,bg=BG);legend.pack(side="left",fill="x",expand=True,padx=7,pady=4)
        self.hotkey_labels=[]
        for line,color in ((self.GLOBAL_HOTKEYS,AMBER),(self.MUSIC_HOTKEYS,CYAN),(self.EDIT_HOTKEYS,MUTED),(self.VISUAL_HOTKEYS,PINK),(self.SOUNDBOARD_HOTKEYS,LIME)):
            label=tk.Label(legend,text=line,fg=color,bg=BG,font=(MONO,7,"bold"),anchor="w",justify="left")
            label.pack(fill="x");self.hotkey_labels.append(label)
        def wrap_hotkeys(event):
            width=max(440,event.width-26)
            for label in self.hotkey_labels:label.configure(wraplength=width)
        legend.bind("<Configure>",wrap_hotkeys)
        tk.Label(foot,text="PIPEWIRE\nNATIVE",fg=LIME,bg=BG,font=(MONO,8,"bold"),justify="right").pack(side="right",padx=7)

    def build_music(self):
        bar=tk.Frame(self.music,bg=PANEL);bar.pack(fill="x",padx=8,pady=8)
        for text,cmd,col,glyph in (("PLAY",self.toggle,LIME,"play"),("GENERATE",self.generate,CYAN,"spark"),("MUTATE",self.mutate,PINK,"cycle"),("ALL STYLES",self.open_style_picker,AMBER,"diamond")):
            button=self.button(bar,text,cmd,col,glyph);button.pack(side="left",padx=2)
            if glyph=="play":self.play_btn=button
        tk.Label(bar,text="STATE",fg=MUTED,bg=PANEL,font=(MONO,9,"bold")).pack(side="left",padx=(8,2))
        tk.Spinbox(bar,from_=0,to=9,textvariable=self.state_slot,width=2,wrap=True,bg=BG,fg=WHITE,buttonbackground=PANEL,
                   insertbackground=WHITE,font=(MONO,10,"bold")).pack(side="left")
        self.button(bar,"SAVE",self.save_state,WHITE,"disk").pack(side="left",padx=2)
        self.button(bar,"LOAD",self.load_state,AMBER,"folder").pack(side="left",padx=2)
        self.button(bar,"EXPORT",self.export,LIME,"download").pack(side="left",padx=2)
        self.button(bar,"WAVE FORGE",self.open_forge,AMBER,"hammer").pack(side="right",padx=2)
        banks=tk.Frame(self.music,bg=PANEL);banks.pack(fill="x",padx=10,pady=(0,4))
        bank_top=tk.Frame(banks,bg=PANEL);bank_top.pack(fill="x")
        tk.Label(bank_top,text="LIVE BANKS",fg=MUTED,bg=PANEL,font=(MONO,8,"bold")).pack(side="left",padx=(0,5))
        for text,style_name,color in (("CHIPTUNE","NEON NOIR",CYAN),("808","808 BOOM BAP",AMBER),
                                      ("VAPOR","MALL AFTER MIDNIGHT",PINK),("LO-FI","RAINY WINDOW BEATS",LIME)):
            self.button(bank_top,text,lambda name=style_name:self.jump_style(name),color,"chip").pack(side="left",padx=2)
        bank_bottom=tk.Frame(banks,bg=PANEL);bank_bottom.pack(fill="x",pady=(3,0))
        tk.Label(bank_bottom,text="CLUB BANKS",fg=MUTED,bg=PANEL,font=(MONO,8,"bold")).pack(side="left",padx=(0,5))
        for text,style_name,color in (("TECHNO","WAREHOUSE PULSE",PINK),("HOUSE","MIDNIGHT HOUSE",LIME),
                                      ("DNB","JUNGLE CIRCUIT",AMBER),("SYNTH","NIGHTDRIVE 84",CYAN)):
            self.button(bank_bottom,text,lambda name=style_name:self.jump_style(name),color,"chip").pack(side="left",padx=2)
        self.tracks_btn=self.button(bank_bottom,"4 CORE",self.toggle_tracks,AMBER,"lanes");self.tracks_btn.pack(side="right",padx=2)
        self.flow_btn=self.button(bank_bottom,"FLOW LAB",self.open_flow_lab,CYAN,"wave");self.flow_btn.pack(side="right",padx=2)
        arranger=tk.Frame(self.music,bg="#0d1822",highlightbackground=CYAN,highlightthickness=1);arranger.pack(fill="x",padx=10,pady=(2,5))
        arrange_bar=tk.Frame(arranger,bg="#0d1822");arrange_bar.pack(fill="x",padx=5,pady=(3,0))
        tk.Label(arrange_bar,text="SONG MAP",fg=CYAN,bg="#0d1822",font=(MONO,10,"bold")).pack(side="left",padx=(2,5))
        self.path_btn=self.button(arrange_bar,f"PATH {self.project.song_path}",self.open_song_path_picker,PINK,"diamond");self.path_btn.pack(side="left",padx=2)
        self.path_hold_btn=self.button(arrange_bar,"LOOP SCENE",self.toggle_path_hold,AMBER,"clock");self.path_hold_btn.pack(side="left",padx=2)
        self.path_next_btn=self.button(arrange_bar,"CUE NEXT",self.queue_next_scene,LIME,"right");self.path_next_btn.pack(side="left",padx=2)
        self.path_home_btn=self.button(arrange_bar,"RETURN HOME",self.queue_home_scene,CYAN,"cycle");self.path_home_btn.pack(side="left",padx=2)
        evolve_bar=tk.Frame(arranger,bg="#0d1822");evolve_bar.pack(fill="x",padx=7,pady=(2,0))
        tk.Label(evolve_bar,text="PATH MOVES THE HARMONY  •  EVOLVE CHANGES DRUMS, FILLS + MELODY DETAILS",fg=MUTED,bg="#0d1822",font=(MONO,8,"bold"),anchor="w").pack(side="left",fill="x",expand=True)
        self.auto_btn=self.button(evolve_bar,"EVOLVE OFF",self.cycle_auto_mutate,PINK,"wave");self.auto_btn.pack(side="right",padx=2)
        self.path_map=tk.Canvas(arranger,height=72,bg="#081018",highlightthickness=0);self.path_map.pack(fill="x",padx=5,pady=(3,5))
        self.build_vox_deck()
        opts=tk.Frame(self.music,bg=PANEL);opts.pack(fill="x",padx=10)
        tk.Label(opts,text="BPM",fg=MUTED,bg=PANEL).pack(side="left")
        tk.Scale(opts,from_=40,to=240,orient="horizontal",variable=self.bpm,command=self.change_tempo,bg=PANEL,fg=WHITE,troughcolor=GRID,highlightthickness=0,length=150).pack(side="left")
        tk.Label(opts,text="SWING",fg=MUTED,bg=PANEL).pack(side="left")
        tk.Scale(opts,from_=0,to=.45,resolution=.01,orient="horizontal",variable=self.swing,command=self.change_swing,bg=PANEL,fg=WHITE,troughcolor=GRID,highlightthickness=0,length=130).pack(side="left")
        self.insert_btn=self.button(opts,"INSERT OFF",self.toggle_insert,PINK,"cursor");self.insert_btn.pack(side="right")
        self.meta=tk.Label(self.music,text="",fg=CYAN,bg=PANEL,font=(MONO,10,"bold"),anchor="w");self.meta.pack(fill="x",padx=12,pady=(6,2))
        self.tracker=tk.Canvas(self.music,bg=BG,highlightthickness=1,highlightbackground=GRID);self.tracker.pack(fill="both",expand=True,padx=8,pady=5)
        nav=tk.Frame(self.music,bg=PANEL);nav.pack(fill="x",padx=8,pady=(2,8))
        self.page_label=tk.Label(nav,text="PAGE 1 / 4",fg=AMBER,bg=PANEL,font=(MONO,10,"bold"));self.page_label.pack(side="left",padx=6)
        self.page_nav_buttons=[]
        for text,cmd,glyph in (("PAGE",lambda:self.move_page(-1),"left"),("PAGE",lambda:self.move_page(1),"right"),("CLEAR CHANNEL",self.clear_channel,"clear"),("AUDITION",self.audition,"speaker")):
            button=self.button(nav,text,cmd,WHITE,glyph);button.pack(side="left",padx=2)
            if text=="PAGE":self.page_nav_buttons.append(button)
        self.meters=tk.Canvas(nav,width=217,height=30,bg=BG,highlightthickness=0);self.meters.pack(side="right")

    def build_vox_deck(self):
        deck=tk.Frame(self.music,bg="#1a0b19",highlightbackground=PINK,highlightthickness=1);deck.pack(fill="x",padx=10,pady=(0,5))
        tk.Label(deck,text="TRACK 7 // SOUNDBOARD",fg=PINK,bg="#1a0b19",font=(MONO,10,"bold")).pack(side="left",padx=(8,6),pady=5)
        self.vox_phrase=tk.Label(deck,text="",fg=WHITE,bg="#1a0b19",font=(MONO,8,"bold"),anchor="w")
        self.vox_phrase.pack(side="left",fill="x",expand=True,padx=4)
        self.vox_auto_btn=self.button(deck,"LOOP",self.cycle_vox_auto,LIME,"cycle");self.vox_auto_btn.pack(side="right",padx=2,pady=3)
        self.vox_mute_btn=self.button(deck,"MUTE",self.vox_mute,WHITE,"speaker");self.vox_mute_btn.pack(side="right",padx=2,pady=3)
        self.button(deck,"OPEN BOARD",self.toggle_soundboard_view,PINK,"grid").pack(side="right",padx=2,pady=3)

    def build_soundboard(self):
        top=tk.Frame(self.soundboard,bg="#100912");top.pack(fill="x",padx=16,pady=(16,8))
        tk.Label(top,text="TRACK 7 // FOUR-BAR SOUNDBOARD",fg=PINK,bg="#100912",font=(MONO,16,"bold")).pack(side="left")
        self.button(top,"BACK TO SPLIT",lambda:self.set_view("split"),AMBER,"left").pack(side="right",padx=2)
        self.board_mute_btn=self.button(top,"MUTE",self.vox_mute,WHITE,"speaker");self.board_mute_btn.pack(side="right",padx=2)

        identity=tk.Frame(self.soundboard,bg="#1a0b19",highlightbackground=PINK,highlightthickness=1);identity.pack(fill="x",padx=16,pady=5)
        self.board_phrase=tk.Label(identity,text="",fg=WHITE,bg="#1a0b19",font=(MONO,12,"bold"),anchor="w")
        self.board_phrase.pack(side="left",fill="x",expand=True,padx=10,pady=8)
        self.board_voice_btn=self.button(identity,"VOICE  WOBBLE",self.cycle_vox_voice,CYAN,"chip");self.board_voice_btn.pack(side="right",padx=2)
        self.board_mode_btn=self.button(identity,"BODY  PUNCH",self.cycle_vox_mode,AMBER,"wave");self.board_mode_btn.pack(side="right",padx=2)

        words_box=tk.Frame(self.soundboard,bg="#13101a",highlightbackground=AMBER,highlightthickness=1);words_box.pack(fill="x",padx=16,pady=5)
        tk.Label(words_box,text="VOCAL WORDS // 1–3",fg=AMBER,bg="#13101a",font=(MONO,10,"bold")).pack(side="left",padx=9,pady=7)
        self.vox_word_buttons=[]
        for slot,color in enumerate((LIME,CYAN,PINK)):
            button=self.button(
                words_box,f"WORD {slot+1}",lambda index=slot:self.cycle_vox_word(index),color,"speaker",
                width=self.VOX_WORD_BUTTON_WIDTH,height=self.VOX_WORD_BUTTON_HEIGHT,
                padx=12,pady=4,font=(MONO,11,"bold"),anchor="center",relief="solid",bd=1,
            )
            button.pack(side="left",padx=3,pady=4);self.vox_word_buttons.append(button)
        self.button(words_box,"RANDOMIZE WORDS",self.randomize_vox_words,PINK,"spark").pack(side="right",padx=3,pady=4)
        self.vox_remove_word_btn=self.button(words_box,"REMOVE LAST",self.remove_vox_word,WHITE,"clear");self.vox_remove_word_btn.pack(side="right",padx=3,pady=4)
        tk.Label(words_box,text="1 = STAB  ·  2 = DEFAULT  ·  3 = CHANT",fg=MUTED,bg="#13101a",font=(MONO,8,"bold")).pack(side="right",padx=10)

        pad_wrap=tk.Frame(self.soundboard,bg="#100912");pad_wrap.pack(fill="x",padx=16,pady=8)

        mode_box=tk.Frame(pad_wrap,bg="#0d1822",highlightbackground=CYAN,highlightthickness=1);mode_box.pack(fill="x",pady=(0,10))
        tk.Label(mode_box,text="PLAY MODE",fg=CYAN,bg="#0d1822",font=(MONO,10,"bold")).pack(side="left",padx=9,pady=7)
        self.board_automation_buttons={}
        for mode,text,color in (("OFF","LIVE ONLY",WHITE),("LOOP","LOOP ON",LIME),("AUTO","AUTO VARIATION",PINK)):
            button=self.button(mode_box,text,lambda value=mode:self.set_vox_automation(value),color,"cycle")
            button.pack(side="left",padx=3,pady=4);self.board_automation_buttons[mode]=button
        self.board_automation_help=tk.Label(mode_box,text="",fg=MUTED,bg="#0d1822",font=(MONO,9,"bold"),anchor="e")
        self.board_automation_help.pack(side="right",fill="x",expand=True,padx=10)

        perform=tk.Frame(pad_wrap,bg="#100912")
        perform.pack(fill="x")
        tk.Label(perform,text="PERFORM // TAP A PAD: IT FIRES ON THE SONG CLOCK AND BECOMES THE PAD YOU CAN PLACE BELOW",fg=MUTED,bg="#100912",font=(MONO,9,"bold")).pack(anchor="w",pady=(0,5))
        pads=tk.Frame(perform,bg="#100912");pads.pack(fill="x")
        self.vox_pad_buttons={}
        colors=(LIME,PINK,AMBER,PINK,CYAN,AMBER,LIME,CYAN)
        glyphs=("speaker","diamond","clear","hammer","wave","clock","right","cycle")
        for index,action in enumerate(VOX_PAD_ACTIONS):
            label=f"{index+1}  {VOX_PAD_LABELS[action]}"
            button=self.button(pads,label,lambda value=action:self.select_vox_pad(value,True),colors[index],glyphs[index],
                               pady=11,font=(MONO,11,"bold"))
            button.grid(row=index//4,column=index%4,sticky="nsew",padx=4,pady=4)
            self.vox_pad_buttons[action]=button
        for column in range(4):pads.grid_columnconfigure(column,weight=1)

        loop_head=tk.Frame(pad_wrap,bg="#100912");loop_head.pack(fill="x",pady=(15,5))
        tk.Label(loop_head,text="PROGRAM // FOUR BARS · FOUR BEATS EACH",fg=PINK,bg="#100912",font=(MONO,10,"bold")).pack(side="left")
        self.vox_selected_label=tk.Label(loop_head,text="",fg=CYAN,bg="#100912",font=(MONO,9,"bold"));self.vox_selected_label.pack(side="left",padx=14)
        self.button(loop_head,"RANDOMIZE LOOP",self.new_vox_pattern,PINK,"spark").pack(side="right",padx=2)
        self.button(loop_head,"CLEAR ALL",self.clear_vox_pattern,WHITE,"clear").pack(side="right",padx=2)
        self.board_loop_summary=tk.Label(loop_head,text="",fg=MUTED,bg="#100912",font=(MONO,8,"bold"));self.board_loop_summary.pack(side="right",padx=10)

        loop_grid=tk.Frame(pad_wrap,bg="#100912");loop_grid.pack(fill="x")
        self.vox_loop_buttons=[]
        for bar in range(4):
            bar_box=tk.Frame(loop_grid,bg="#120f18",highlightbackground=GRID,highlightthickness=1)
            bar_box.grid(row=0,column=bar,sticky="nsew",padx=4)
            tk.Label(bar_box,text=f"BAR {bar+1}",fg=AMBER,bg="#120f18",font=(MONO,9,"bold")).pack(fill="x",pady=(5,2))
            beats=tk.Frame(bar_box,bg="#120f18");beats.pack(fill="x",padx=4,pady=(0,5))
            for beat in range(4):
                index=bar*4+beat
                button=tk.Button(beats,text=f"{beat+1}\n—",command=lambda cell=index:self.toggle_vox_step(cell),
                                 bg=PANEL,fg=MUTED,activebackground=PINK,activeforeground=BG,
                                 relief="flat",bd=0,padx=4,pady=8,font=(MONO,10,"bold"),height=2)
                button.pack(side="left",fill="x",expand=True,padx=2)
                self.vox_loop_buttons.append(button)
        for column in range(4):loop_grid.grid_columnconfigure(column,weight=1)

        guide=tk.Frame(pad_wrap,bg="#0b1118",highlightbackground=GRID,highlightthickness=1);guide.pack(fill="x",pady=(12,0))
        for number,title,detail,color in (("1","TAP A PAD","Hear it on the next beat",LIME),("2","CLICK A BEAT","Empty adds it; filled removes it",CYAN),("3","CHOOSE MODE","Loop it yourself or let Auto vary it",PINK)):
            card=tk.Frame(guide,bg="#0b1118");card.pack(side="left",fill="x",expand=True,padx=10,pady=7)
            tk.Label(card,text=f"{number}  {title}",fg=color,bg="#0b1118",font=(MONO,9,"bold")).pack(anchor="w")
            tk.Label(card,text=detail,fg=MUTED,bg="#0b1118",font=(MONO,8)).pack(anchor="w")

    def build_visual(self):
        bar=tk.Frame(self.visual,bg=PANEL);bar.pack(fill="x",padx=8,pady=8)
        controls=(("VIS",lambda:self.vis.cycle_scene(-1),"left"),("VIS",self._next_vis,"right"),("MUTATE",self._mutate_vis,"cycle"),("LOOK",self._look,"eye"),("FX",self._fx,"spark"),("8-BIT",self._pixel,"grid"),("HUD",self._hud,"screen"),("TAKEOVER",self.toggle_visual_view,"expand"))
        for text,cmd,glyph in controls:self.button(bar,text,cmd,PINK if text.startswith(("MUTATE","LOOK")) else CYAN,glyph).pack(side="left",padx=2)
        self.vis=Visualizer(self.visual,self.audio);self.vis.pack(fill="both",expand=True,padx=8,pady=(0,8))
        self.vis.bind("<Button-1>",lambda e:self.set_focus("visual"))

    def bind(self):
        self.root.bind("<F6>",lambda e:self.switch_focus());self.root.bind("<F11>",lambda e:self.fullscreen())
        self.root.bind("<Escape>",lambda e:self.escape());self.root.bind("<F1>",lambda e:self.help())
        self.root.bind("<Key>",self.key);self.tracker.bind("<Button-1>",self.click_tracker)
    def key(self,e):
        k=e.keysym; ch=e.char
        if k in ("F6","F11","F1","Escape"):return
        if self.focus_side=="soundboard":
            if ch in "12345678":self.select_vox_pad(VOX_PAD_ACTIONS[int(ch)-1],True)
            elif ch.lower()=="q":self.new_vox_pattern()
            elif ch.lower()=="r":self.randomize_vox_words()
            elif ch.lower()=="c":self.clear_vox_pattern()
            elif ch.lower()=="a":self.cycle_vox_auto()
            elif ch.lower()=="v":self.cycle_vox_voice()
            elif ch.lower()=="m":self.cycle_vox_mode()
            elif k=="space":self.toggle()
            return
        if self.focus_side=="visual":
            if k=="Left":self.vis.cycle_scene(-1)
            elif k=="Right":self.vis.cycle_scene(1)
            elif ch.lower()=="r":self.vis.mutate()
            elif ch.lower()=="l":self.vis.cycle_look()
            elif ch.lower()=="e":self.vis.cycle_fx()
            elif ch=="8":self.vis.pixel=not self.vis.pixel
            elif ch.lower()=="h":self.vis.hud=not self.vis.hud
            elif ch.lower()=="f":self.toggle_visual_view()
            return
        if k=="space":self.toggle()
        elif k=="Tab":self.channel=(self.channel+1)%CHANNEL_COUNT
        elif k=="Left":self.channel=(self.channel-1)%CHANNEL_COUNT
        elif k=="Right":self.channel=(self.channel+1)%CHANNEL_COUNT
        elif k=="Up":self.row=(self.row-1)%64;self.page=self.row//16
        elif k=="Down":self.row=(self.row+1)%64;self.page=self.row//16
        elif k in ("Prior","bracketleft"):self.move_page(-1)
        elif k in ("Next","bracketright"):self.move_page(1)
        elif ch.lower()=="i":self.toggle_insert()
        elif self.insert and ch in "23456":self.octave=int(ch)
        elif self.insert and (ch.lower() in NOTE_KEYS):self.enter_note(ch.lower())
        elif self.insert and k in ("BackSpace","Delete"):self.erase_step()
        elif ch.lower()=="g":self.generate()
        elif ch.lower()=="m":self.mutate()
        elif ch.lower()=="a":self.cycle_auto_mutate()
        elif ch.lower()=="p":self.open_song_path_picker()
        elif ch.lower()=="n":self.queue_next_scene()
        elif ch.lower()=="o":self.queue_home_scene()
        elif ch.lower()=="t":self.toggle_path_hold()
        elif ch=="7":self.toggle_soundboard_view()
        elif ch.lower()=="v":self.vox_call()
        elif ch.lower()=="b":self.vox_bend()
        elif ch.lower()=="y":self.open_style_picker()
        elif ch.lower()=="w":self.open_forge()
        elif ch.lower()=="s":self.save_state()
        elif ch.lower()=="e":self.export()
        elif ch.lower()=="h":self.help()
        elif ch.lower()=="f":self.open_flow_lab()

    def set_focus(self,side):
        self.focus_side=side
        self.music.configure(highlightbackground=LIME if side=="music" else GRID,highlightthickness=2 if side=="music" else 1)
        self.visual.configure(highlightbackground=PINK if side=="visual" else GRID,highlightthickness=2 if side=="visual" else 1)
        self.soundboard.configure(highlightbackground=PINK if side=="soundboard" else GRID,highlightthickness=2 if side=="soundboard" else 1)
        self.status.set(f"FOCUS: {side.upper()}")
    def switch_focus(self):
        if self.view_mode=="deck":self.set_view("visual")
        elif self.view_mode=="visual":self.set_view("deck")
        elif self.view_mode=="soundboard":self.set_view("deck")
        else:self.set_focus("visual" if self.focus_side=="music" else "music")
    def escape(self):
        try:fullscreen=bool(int(self.root.attributes("-fullscreen")))
        except (TypeError,ValueError,tk.TclError):fullscreen=False
        if fullscreen:self.root.attributes("-fullscreen",False);self.status.set("APP FULLSCREEN OFF")
        elif self.view_mode!="split":self.set_view("split")
    def fullscreen(self):
        try:active=bool(int(self.root.attributes("-fullscreen")))
        except (TypeError,ValueError,tk.TclError):active=False
        self.root.attributes("-fullscreen",not active);self.status.set(f"APP FULLSCREEN {'OFF' if active else 'ON'}")
    def cycle_view(self):
        modes=("split","deck","visual","soundboard");self.set_view(modes[(modes.index(self.view_mode)+1)%len(modes)])
    def toggle_visual_view(self):self.set_view("split" if self.view_mode=="visual" else "visual")
    def toggle_deck_view(self):self.set_view("split" if self.view_mode=="deck" else "deck")
    def toggle_soundboard_view(self):self.set_view("split" if self.view_mode=="soundboard" else "soundboard")
    def set_view(self,mode):
        if mode not in ("split","deck","visual","soundboard"):return
        # Python 3.14/Tk 9 may return unhashable Tcl_Obj wrappers here instead
        # of ordinary strings. Normalize before membership tests so the view
        # toggle behaves identically across the development and Steam runtimes.
        managed={str(item) for item in self.pane.panes()}
        for child in (self.music,self.visual,self.soundboard):
            if str(child) in managed:self.pane.forget(child)
        if mode in ("split","deck"):self.pane.add(self.music,stretch="always",minsize=430)
        if mode in ("split","visual"):self.pane.add(self.visual,stretch="always",minsize=430)
        if mode=="soundboard":self.pane.add(self.soundboard,stretch="always",minsize=700)
        self.view_mode=mode;self.view_btn.configure(text=f"VIEW {mode.upper()}")
        self.set_focus("soundboard" if mode=="soundboard" else "visual" if mode=="visual" else "music")
        if mode=="split":self.root.after_idle(lambda:self.pane.sash_place(0,max(430,self.pane.winfo_width()//2),1))
        self.status.set("SPLIT VIEW" if mode=="split" else "DECK TAKEOVER // ALL FOUR PAGES" if mode=="deck" else "VISUAL TAKEOVER" if mode=="visual" else "TRACK 7 SOUNDBOARD // FOUR-BAR LOOP")
    def toggle(self):
        self.core.toggle()
        self.play_btn.configure(text="STOP" if self.core.playing else "PLAY")
        self.status.set("PLAY" if self.core.playing else "STOP")
    def cycle_vox_voice(self):
        current=self.project.vox.voice if self.project.vox.voice in VOX_VOICES else VOX_VOICES[0]
        self.project.vox.voice=VOX_VOICES[(VOX_VOICES.index(current)+1)%len(VOX_VOICES)]
        self.status.set(f"VOX VOICE // {self.project.vox.voice}")
    def cycle_vox_mode(self):
        current=self.project.vox.mode if self.project.vox.mode in VOX_MODES else VOX_MODES[0]
        self.project.vox.mode=VOX_MODES[(VOX_MODES.index(current)+1)%len(VOX_MODES)]
        self.status.set(f"VOX MODE // {self.project.vox.mode}")
    def cycle_vox_auto(self):
        current=self.project.vox.automation if self.project.vox.automation in VOX_AUTOMATION else VOX_AUTOMATION[0]
        self.set_vox_automation(VOX_AUTOMATION[(VOX_AUTOMATION.index(current)+1)%len(VOX_AUTOMATION)])
    def set_vox_automation(self,mode):
        if mode not in VOX_AUTOMATION:return
        self.project.vox.automation=mode
        detail={"OFF":"LIVE PADS ONLY","LOOP":"FIXED FOUR-BAR LOOP","AUTO":"NEW SPARSE LOOP EACH SONG SCENE"}[mode]
        self.status.set(f"TRACK 7 {mode} // {detail}")
    def vox_new_phrase(self,response=False,action="CALL"):
        self.vox_variation=getattr(self,"vox_variation",0)+1
        self.project.vox.phrase=generate_vox_phrase(self.project,self.vox_variation,response=response,action=action)
        return self.project.vox.phrase
    def new_vox_line(self):
        self.randomize_vox_words()
    def edit_vox_phrase(self):
        # Retained as a compatibility entry point for older integrations.
        self.randomize_vox_words()
    def cycle_vox_word(self,index):
        words=parse_vox_words(self.project.vox.phrase) or ["OH","AH"]
        if index<len(words):
            current=words[index];words[index]=VOX_WORDS[(VOX_WORDS.index(current)+1)%len(VOX_WORDS)]
        elif index==len(words) and len(words)<3:
            preferred=("AH","HEY","OH")
            words.append(next((word for word in preferred if word!=words[-1]),"OH"))
        else:return
        self.project.vox.phrase=" / ".join(words[:3])
        self.status.set(f"VOCAL WORDS // {self.project.vox.phrase}")
    def remove_vox_word(self):
        words=parse_vox_words(self.project.vox.phrase) or ["OH","AH"]
        if len(words)<=1:
            self.status.set("VOCAL WORDS // ONE WORD MINIMUM");return
        words.pop();self.project.vox.phrase=" / ".join(words)
        self.status.set(f"VOCAL WORDS // {self.project.vox.phrase}")
    def randomize_vox_words(self):
        phrase=self.vox_new_phrase();self.status.set(f"RANDOM VOCAL WORDS // {phrase}")
    def new_vox_pattern(self):
        self.vox_variation=getattr(self,"vox_variation",0)+1
        self.project.vox.loop=generate_vox_loop(self.project,self.vox_variation)
        self.status.set(f"NEW TRACK 7 LOOP // {sum(item!='---' for item in self.project.vox.loop)} HITS / 4 BARS // WORDS LOCKED {self.project.vox.phrase}")
    def clear_vox_pattern(self):
        self.project.vox.loop=["---"]*16;self.status.set("TRACK 7 LOOP CLEARED // LIVE PADS STILL READY")
    def select_vox_pad(self,action,fire=False):
        if action not in VOX_PAD_ACTIONS:return
        self.vox_selected_action=action
        if fire:self.trigger_vox_pad(action)
    def trigger_vox_pad(self,action):
        quantize="turn" if action=="HOOK" else "gap" if action=="ANSWER" else "beat"
        self.core.queue_vox(action,quantize=quantize)
        boundary="BEAT-FOUR PICKUP" if quantize=="turn" else "NEXT LEAD GAP" if quantize=="gap" else "NEXT BEAT"
        self.status.set(f"PAD {VOX_PAD_LABELS[action]} QUEUED // {boundary}")
    def toggle_vox_step(self,index):
        if not 0<=index<16:return
        action=self.vox_selected_action if self.vox_selected_action in VOX_PAD_ACTIONS else "WUB"
        # A filled cell always clears in one click. An empty cell receives the
        # last pad the performer touched; no invisible match-to-clear rule.
        self.project.vox.loop[index]=action if self.project.vox.loop[index]=="---" else "---"
        placed=self.project.vox.loop[index]
        self.status.set(f"TRACK 7 BAR {index//4+1} BEAT {index%4+1} // {VOX_PAD_LABELS.get(placed,'CLEARED')}")
    def vox_call(self):
        self.select_vox_pad("CALL",True)
    def vox_hook(self):
        self.select_vox_pad("HOOK",True)
    def vox_chop(self):
        self.select_vox_pad("CHOP",True)
    def vox_bend(self):
        if self.core.vox.active:
            self.core.vox.punch_bend();self.status.set("VOX LIVE BEND // PITCH FALL + CRUSH")
        else:
            self.select_vox_pad("BEND",True)
    def vox_echo(self):
        if self.core.vox.active:
            self.core.vox.punch_echo();self.status.set("VOX THROW // LIVE")
        else:
            self.select_vox_pad("ECHO",True)
    def vox_freeze(self):
        self.select_vox_pad("FREEZE",True)
    def vox_answer(self):
        self.select_vox_pad("ANSWER",True)
    def vox_mute(self):
        self.project.vox.muted=not self.project.vox.muted
        if self.project.vox.muted:self.core.vox.stop();self.core.vox_pending=None
        self.status.set(f"VOX {'MUTED' if self.project.vox.muted else 'LIVE'}")
    def update_vox_deck(self):
        pending_action=self.core.vox_pending[0] if self.core.vox_pending else None
        pending=f"  •  QUEUED {VOX_PAD_LABELS.get(pending_action,pending_action)}" if pending_action else ""
        playing=f"  •  PLAYING {VOX_PAD_LABELS.get(self.core.vox.action,self.core.vox.action)}" if self.core.vox.active else ""
        hits=[f"B{index//4+1}.{index%4+1} {VOX_PAD_LABELS[action]}" for index,action in enumerate(self.project.vox.loop) if action in VOX_PAD_ACTIONS]
        summary=" · ".join(hits) if hits else "EMPTY LOOP"
        self.vox_phrase.configure(text=f'{self.project.vox.voice}  //  {summary}{pending}{playing}')
        self.vox_auto_btn.configure(text=self.project.vox.automation)
        self.vox_mute_btn.configure(text="UNMUTE" if self.project.vox.muted else "MUTE")
        hit_count=len(hits);hit_word="HIT" if hit_count==1 else "HITS"
        self.board_phrase.configure(text=f'SHAPE  {self.project.vox.phrase}  //  {hit_count} {hit_word} / 4 BARS{pending}{playing}')
        self.board_voice_btn.configure(text=f"VOICE  {self.project.vox.voice}");self.board_mode_btn.configure(text=f"BODY  {self.project.vox.mode}")
        self.board_mute_btn.configure(text="UNMUTE" if self.project.vox.muted else "MUTE")
        words=parse_vox_words(self.project.vox.phrase) or ["OH","AH"]
        for index,button in enumerate(self.vox_word_buttons):
            if index<len(words):
                button.configure(text=f"{index+1}  ·  {words[index]}",state="normal",bg="#172119",relief="solid",bd=1)
            elif index==len(words) and len(words)<3:
                button.configure(text=f"{index+1}  ·  + ADD",state="normal",bg="#221b0f",relief="solid",bd=1)
            else:
                button.configure(text=f"{index+1}  ·  —",state="disabled",bg=PANEL,relief="flat",bd=0)
        self.vox_remove_word_btn.configure(state="normal" if len(words)>1 else "disabled")
        selected=self.vox_selected_action if self.vox_selected_action in VOX_PAD_ACTIONS else "WUB"
        self.vox_selected_label.configure(text=f"LAST PAD: {VOX_PAD_LABELS[selected]}  //  CLICK EMPTY BEAT TO ADD")
        mode=self.project.vox.automation
        mode_help={"OFF":"Only pad taps play; the programmed loop is paused.",
                   "LOOP":"The visible four-bar pattern repeats exactly.",
                   "AUTO":"The pattern stays sparse and changes with each Song Map scene."}[mode]
        self.board_automation_help.configure(text=mode_help)
        for value,button in self.board_automation_buttons.items():
            active=value==mode
            button.configure(relief="solid" if active else "flat",bd=1 if active else 0,
                             bg="#173326" if active else PANEL)
        self.board_loop_summary.configure(text="CLICK FILLED BEAT = REMOVE")
        live_beat=self.core.current_row//4 if self.core.playing else -1
        for index,button in enumerate(self.vox_loop_buttons):
            action=self.project.vox.loop[index]
            occupied=action in VOX_PAD_ACTIONS
            button.configure(text=f"{index%4+1}\n{VOX_PAD_LABELS.get(action,'—')}",
                             fg=PINK if index==live_beat else CYAN if occupied else MUTED,
                             bg="#2a1025" if index==live_beat else "#102329" if occupied else PANEL,
                             relief="solid" if occupied else "flat",bd=1 if occupied else 0)
        for action,button in self.vox_pad_buttons.items():
            button.configure(relief="solid" if action==selected else "flat",bd=1 if action==selected else 0)
    def sync_flow_project(self):
        self.project.randomness=clamp(self.randomness.get()/100.0,0.0,1.0)
        self.project.harmonic_motion=clamp(self.harmonic_motion.get()/100.0,0.0,1.0)
        target=self.blend_target.get();self.project.blend_style="" if target=="NO BLEND" else target
        self.project.blend_amount=0.0 if not self.project.blend_style else clamp(self.blend_amount.get()/100.0,0.0,1.0)
        self.project.track_count=6 if self.track_count.get()>=6 else 4
    def blend_style_index(self):
        return next((i for i,item in enumerate(STYLES) if item["name"]==self.project.blend_style),None)
    def smooth_change(self,action,label="CHANGE"):
        if self.transition_busy:return
        self.transition_busy=True;self.status.set(f"{label} // CROSSFADING");self.core.set_output_gain(0.0)
        def apply():
            try:action()
            finally:self.core.set_output_gain(1.0);self.root.after(180,self._finish_transition)
        self.root.after(170,apply)
    def _finish_transition(self):self.transition_busy=False
    def generate(self,seed=None):
        self.smooth_change(lambda:self._generate_now(seed),"GENERATE")
    def _generate_now(self,seed=None):
        self.sync_flow_project();self.core.stop()
        generate_song(self.project,self.style_index,seed=seed,randomness=self.project.randomness,
                      harmonic_motion=self.project.harmonic_motion,blend_style_index=self.blend_style_index(),
                      blend_amount=self.project.blend_amount,track_count=self.project.track_count)
        self.blend_target.set(self.project.blend_style or "NO BLEND");self.blend_amount.set(self.project.blend_amount*100)
        self.capture_theme();self.vis.match_style(self.project.style);self.core.reseed();self.core.start(0);self.play_btn.configure(text="STOP");self.auto_last_cycle=0
        self.status.set(f"GENERATED {self.project.title} // {self.project.progression} // {self.project.track_count} TRACKS")
    def regenerate_same_seed(self):self.generate(seed=self.project.seed)
    def toggle_tracks(self):
        self.track_count.set(6 if self.track_count.get()<6 else 4);self.regenerate_same_seed()
    def open_flow_lab(self):
        if self.flow_window is not None and self.flow_window.winfo_exists():self.flow_window.lift();self.flow_window.focus_force();return
        win=tk.Toplevel(self.root,bg=BG);self.apply_window_icon(win);self.flow_window=win;win.title("CHIPFORGE FLOW LAB");win.geometry("590x570");win.minsize(520,520)
        tk.Label(win,text="FLOW GENERATION LAB",fg=CYAN,bg=BG,font=(MONO,16,"bold")).pack(anchor="w",padx=18,pady=(18,4))
        tk.Label(win,text="Bounded controls: every note remains inside the song's scale and progression.",fg=MUTED,bg=BG,font=(MONO,9),wraplength=540,justify="left").pack(anchor="w",padx=18,pady=(0,14))
        def slider(label,var,description):
            frame=tk.Frame(win,bg=BG);frame.pack(fill="x",padx=18,pady=5)
            tk.Label(frame,text=label,fg=WHITE,bg=BG,font=(MONO,10,"bold"),width=18,anchor="w").pack(side="left")
            tk.Scale(frame,from_=0,to=100,resolution=1,orient="horizontal",variable=var,bg=BG,fg=WHITE,troughcolor=GRID,highlightthickness=0,length=300).pack(side="right",fill="x",expand=True)
            tk.Label(win,text=description,fg=MUTED,bg=BG,font=(MONO,8),anchor="w",justify="left",wraplength=540).pack(fill="x",padx=24)
        slider("RANDOMNESS",self.randomness,"Performance density, rhythmic choices, motif transformations and timbre variation—never out-of-key note soup.")
        slider("MUSIC MATH",self.harmonic_motion,"Low values hover near home; high values choose stronger functional travel and cadences.")
        blend=tk.Frame(win,bg=BG);blend.pack(fill="x",padx=18,pady=(12,4));tk.Label(blend,text="BLEND TARGET",fg=WHITE,bg=BG,font=(MONO,10,"bold"),width=18,anchor="w").pack(side="left")
        ttk.Combobox(blend,textvariable=self.blend_target,values=("NO BLEND",)+tuple(item["name"] for item in STYLES),state="readonly").pack(side="right",fill="x",expand=True)
        slider("BLEND AMOUNT",self.blend_amount,"Morph tempo, swing, density, key center and synth families into the target style.")
        lanes=tk.Frame(win,bg=BG);lanes.pack(fill="x",padx=18,pady=12);tk.Label(lanes,text="ARRANGEMENT",fg=WHITE,bg=BG,font=(MONO,10,"bold"),width=18,anchor="w").pack(side="left")
        for value,text in ((4,"4 CORE"),(6,"6 FULL  + PERC / AIR")):
            tk.Radiobutton(lanes,text=text,variable=self.track_count,value=value,bg=BG,fg=AMBER,selectcolor=PANEL,activebackground=BG,activeforeground=WHITE,font=(MONO,9,"bold")).pack(side="left",padx=4)
        buttons=tk.Frame(win,bg=BG);buttons.pack(fill="x",padx=18,pady=16)
        self.button(buttons,"GENERATE NEW FLOW",self.generate,LIME,"spark").pack(side="left")
        self.button(buttons,"REBUILD SAME SEED",self.regenerate_same_seed,AMBER,"cycle").pack(side="left",padx=6)
        def closed():self.flow_window=None;win.destroy()
        self.button(buttons,"CLOSE",closed,WHITE,"clear").pack(side="right")
        win.protocol("WM_DELETE_WINDOW",closed)
    def mutate(self):
        self.smooth_change(self._mutate_now,"MUTATE")
    def _mutate_now(self):
        self.sync_flow_project();amount=.06+self.project.randomness*.20
        with self.core.lock:changes=mutate_song(self.project,amount=amount);self.capture_theme()
        self.status.set(f"MUTATED {changes} EVENTS // NEW PRIMARY THEME")
    def open_style_picker(self):
        if self.style_window is not None and self.style_window.winfo_exists():self.style_window.lift();self.style_window.focus_force();return
        win=tk.Toplevel(self.root,bg=BG);self.apply_window_icon(win);self.style_window=win;win.title("ALL CHIPFORGE STYLES");win.geometry("820x610");win.minsize(650,520)
        tk.Label(win,text="ALL STYLES",fg=AMBER,bg=BG,font=(MONO,16,"bold")).pack(anchor="w",padx=18,pady=(18,4))
        tk.Label(win,text="The bank buttons are fast live shortcuts. This chooser exposes every complete sound machine.",fg=MUTED,bg=BG,font=(MONO,9)).pack(anchor="w",padx=18,pady=(0,12))
        grid=tk.Frame(win,bg=BG);grid.pack(fill="both",expand=True,padx=16)
        for index,style in enumerate(STYLES):
            current=index==self.style_index;color=LIME if current else CYAN
            button=self.button(grid,style["name"],lambda name=style["name"]:self.jump_style(name),color,"chip",width=22,anchor="w")
            button.grid(row=index//3,column=index%3,sticky="ew",padx=3,pady=3)
        for column in range(3):grid.grid_columnconfigure(column,weight=1)
        def closed():self.style_window=None;win.destroy()
        self.button(win,"CLOSE",closed,WHITE,"clear").pack(anchor="e",padx=18,pady=12);win.protocol("WM_DELETE_WINDOW",closed)
    def style(self):self.open_style_picker()
    def jump_style(self,name):
        self.style_index=next(i for i,style in enumerate(STYLES) if style["name"]==name)
        if self.style_window is not None and self.style_window.winfo_exists():self.style_window.destroy();self.style_window=None
        self.generate()
    def capture_theme(self):
        self.theme_anchor=self.project.clone();self.song_path_anchor=self.project.clone()
        self.song_scene_index=0;self.song_path_queued=None;self.song_path_event=None
        self.auto_variation=0;self.auto_last_cycle=self.core.completed_cycles
        self._rebuild_song_path()

    def _rebuild_song_path(self):
        if self.project.song_path not in SONG_PATHS:self.project.song_path="LIFT"
        tokens=SONG_PATHS[self.project.song_path]
        self.song_scenes=[(token,build_song_scene(self.song_path_anchor,token)) for token in tokens]

    @staticmethod
    def _copy_pattern(project):
        return [[Step(step.note,step.velocity,step.effect) for step in channel] for channel in project.pattern]

    def _apply_song_scene_locked(self,index):
        if not self.song_scenes:return
        self.song_scene_index=index%len(self.song_scenes)
        token,scene=self.song_scenes[self.song_scene_index]
        self.project.pattern=self._copy_pattern(scene);self.project.progression=scene.progression
        self.theme_anchor=self.project.clone();self.auto_variation=0;self.auto_last_cycle=self.core.completed_cycles
        if self.project.vox.automation=="AUTO":
            # AUTO changes the pad pattern at the four-bar scene boundary; it
            # never injects an extra unscheduled vocal or overwrites the chosen
            # one-to-three-word chant. Words and loop automation are independent.
            self.vox_variation+=1
            self.project.vox.loop=generate_vox_loop(self.project,self.vox_variation)
        self.song_path_event=(token,scene.progression)

    def _audio_cycle_boundary(self,_completed_cycles):
        if self.song_path_queued is not None:return
        if self.path_hold or not self.project.song_path_enabled or not self.song_scenes:return
        self._apply_song_scene_locked((self.song_scene_index+1)%len(self.song_scenes))

    def _audio_bar_boundary(self,_bar,_completed_cycles):
        if self.song_path_queued is None:return
        target=self.song_path_queued;self.song_path_queued=None
        self._apply_song_scene_locked(target)

    def _queue_scene(self,index):
        index%=max(1,len(self.song_scenes));token=self.song_scenes[index][0]
        if self.core.playing:
            if self.song_path_queued==index:
                self.song_path_queued=None;self.status.set("SCENE CUE CANCELED")
            else:
                self.song_path_queued=index;self.status.set(f"QUEUED {self.scene_display_name(index)} // LANDS NEXT BAR")
        else:
            with self.core.lock:self._apply_song_scene_locked(index)
            self.status.set(f"SONG MAP {self.project.song_path} // {self.scene_display_name(index)} READY")

    def scene_display_name(self,index):
        names=SONG_PATH_SCENE_NAMES.get(self.project.song_path,SONG_PATHS.get(self.project.song_path,("A",)))
        return names[index%len(names)]

    def open_song_path_picker(self):
        if self.path_window is not None and self.path_window.winfo_exists():self.path_window.lift();self.path_window.focus_force();return
        win=tk.Toplevel(self.root,bg=BG);self.apply_window_icon(win);self.path_window=win;win.title("CHOOSE SONG PATH");win.geometry("650x500");win.minsize(560,440)
        tk.Label(win,text="CHOOSE A SONG PATH",fg=CYAN,bg=BG,font=(MONO,16,"bold")).pack(anchor="w",padx=18,pady=(18,4))
        tk.Label(win,text="Each path is four related harmonic scenes. Automatic moves land every four bars; manual cues land on the next bar.",fg=MUTED,bg=BG,font=(MONO,9),wraplength=610,justify="left").pack(anchor="w",padx=18,pady=(0,12))
        descriptions={
            "LOOP":"Steady groove with a repeating variation.","LIFT":"Familiar groove, rising change, contrast, then home.",
            "JOURNEY":"The clearest departure, climax and return.","BUILD":"Low energy into tension and a full drop.",
            "VERSE/HOOK":"Song form for hip-hop, pop and vocal space.","DREAM":"Drifting harmony with an airy breakdown and return.",
        }
        for name in SONG_PATHS:
            row=tk.Frame(win,bg=PANEL,highlightbackground=CYAN if name==self.project.song_path else GRID,highlightthickness=1);row.pack(fill="x",padx=18,pady=3)
            self.button(row,name,lambda selected=name:self.select_song_path(selected),PINK if name==self.project.song_path else CYAN,"diamond",width=13).pack(side="left",padx=5,pady=5)
            stages="  →  ".join(SONG_PATH_SCENE_NAMES[name])
            text=tk.Frame(row,bg=PANEL);text.pack(side="left",fill="x",expand=True,padx=5,pady=4)
            tk.Label(text,text=stages,fg=LIME,bg=PANEL,font=(MONO,9,"bold"),anchor="w").pack(fill="x")
            tk.Label(text,text=descriptions[name],fg=MUTED,bg=PANEL,font=(MONO,8),anchor="w").pack(fill="x")
        def closed():self.path_window=None;win.destroy()
        self.button(win,"CLOSE",closed,WHITE,"clear").pack(anchor="e",padx=18,pady=12);win.protocol("WM_DELETE_WINDOW",closed)

    def select_song_path(self,name):
        if name not in SONG_PATHS:return
        self.project.song_path=name;self._rebuild_song_path();self.song_scene_index=0;self._queue_scene(0)
        if self.path_window is not None and self.path_window.winfo_exists():self.path_window.destroy();self.path_window=None

    def queue_next_scene(self):
        self._queue_scene((self.song_scene_index+1)%max(1,len(self.song_scenes)))

    def queue_home_scene(self):
        tokens=SONG_PATHS.get(self.project.song_path,("A",))
        target=next((index for index,token in enumerate(tokens) if token=="HOME"),0);self._queue_scene(target)

    def toggle_path_hold(self):
        self.path_hold=not self.path_hold;self.project.song_path_enabled=not self.path_hold
        self.status.set("LOOPING CURRENT SCENE // MANUAL CUES STILL ACTIVE" if self.path_hold else "SONG PATH RUNNING // AUTOMATIC FOUR-BAR MOVES")

    def update_path_controls(self):
        if not self.song_scenes:return
        next_index=self.song_path_queued if self.song_path_queued is not None else (self.song_scene_index+1)%len(self.song_scenes)
        self.path_btn.configure(text=f"PATH {self.project.song_path}")
        self.path_hold_btn.configure(text="RUN PATH" if self.path_hold else "LOOP SCENE")
        self.path_next_btn.configure(text=f"QUEUED {self.scene_display_name(next_index)}" if self.song_path_queued is not None else "CUE NEXT")
        home_tokens=SONG_PATHS.get(self.project.song_path,("A",));home_index=next((index for index,token in enumerate(home_tokens) if token=="HOME"),0)
        home_disabled=self.project.pattern==self.song_scenes[home_index][1].pattern and self.song_path_queued is None
        self.path_home_btn.configure(state="disabled" if home_disabled else "normal")
        self.draw_song_map()

    def draw_song_map(self):
        c=self.path_map;c.delete("all");w=max(420,c.winfo_width());h=max(68,c.winfo_height());gap=9;pad=7;card_w=(w-pad*2-gap*3)/4
        names=SONG_PATH_SCENE_NAMES.get(self.project.song_path,SONG_PATHS[self.project.song_path])
        rows_until_bar=16-self.core.current_row%16;beats=max(1,math.ceil(rows_until_bar/4))
        for index,((token,scene),name) in enumerate(zip(self.song_scenes,names)):
            x=pad+index*(card_w+gap);active=index==self.song_scene_index;queued=index==self.song_path_queued
            fill="#10313a" if active else "#102919" if queued else "#0a141d";outline=CYAN if active else LIME if queued else GRID
            c.create_rectangle(x,4,x+card_w,h-5,fill=fill,outline=outline,width=3 if active or queued else 1)
            c.create_text(x+8,13,anchor="w",text=f"{index+1}  {name}",fill=CYAN if active else LIME if queued else WHITE,font=(MONO,9,"bold"))
            c.create_text(x+8,33,anchor="w",text=f"{token}  {scene.progression}",fill=WHITE if active or queued else MUTED,font=(MONO,7,"bold"))
            state="PLAYING" if active else f"QUEUED · {beats} BEAT{'S' if beats!=1 else ''}" if queued else "UP NEXT" if index==(self.song_scene_index+1)%4 else ""
            c.create_text(x+8,51,anchor="w",text=state,fill=CYAN if active else LIME if queued else AMBER,font=(MONO,7,"bold"))
            if active and self.core.playing:
                progress=(self.core.current_row%16)/16;c.create_rectangle(x+3,h-9,x+3+(card_w-6)*progress,h-6,fill=PINK,outline="")
    def cycle_auto_mutate(self):
        was_off=self.AUTO_LOOP_INTERVALS[self.auto_interval_index]==0
        self.auto_interval_index=(self.auto_interval_index+1)%len(self.AUTO_LOOP_INTERVALS)
        interval=self.AUTO_LOOP_INTERVALS[self.auto_interval_index]
        if was_off and interval:
            self.theme_anchor=self.project.clone();self.auto_variation=0
        self.auto_last_cycle=self.core.completed_cycles
        if interval:
            self.status.set(f"EVOLVE EVERY {interval*4} BARS // CHANGES DETAILS INSIDE THE ACTIVE SCENE")
        else:
            self.status.set("EVOLVE OFF // SONG PATH HARMONY CONTINUES")
        self.update_auto_button()
    def update_auto_button(self):
        interval=self.AUTO_LOOP_INTERVALS[self.auto_interval_index]
        if not interval:
            self.auto_btn.configure(text="EVOLVE OFF")
            return
        elapsed=max(0,self.core.completed_cycles-self.auto_last_cycle)*self.project.rows+self.core.current_row
        bars=max(1,math.ceil(max(0,interval*self.project.rows-elapsed)/16))
        self.auto_btn.configure(text=f"EVOLVE {interval*4}B · {bars}B")
    def maybe_auto_mutate(self):
        interval=self.AUTO_LOOP_INTERVALS[self.auto_interval_index]
        if not interval or not self.core.playing:return
        with self.core.lock:
            elapsed=self.core.completed_cycles-self.auto_last_cycle
            if elapsed < interval:return
            due=max(1,elapsed//interval);self.auto_variation+=due;self.auto_last_cycle+=due*interval
            changes=theme_variation(self.project,self.theme_anchor,self.auto_variation)
        phase=(self.auto_variation-1)%8+1
        if changes:
            self.status.set(f"EVOLVE {phase}/8 // {changes} DETAIL CHANGES // HARMONY HELD")
        else:
            self.status.set("EVOLVE 8/8 // ORIGINAL PERFORMANCE RETURNS")
    def change_tempo(self,_=None):self.project.bpm=int(self.bpm.get())
    def change_swing(self,_=None):self.project.swing=float(self.swing.get())
    def toggle_insert(self):self.insert=not self.insert;self.insert_btn.configure(text=f"INSERT {'ON' if self.insert else 'OFF'}")
    def move_page(self,d):self.page=(self.page+d)%4;self.row=self.page*16+self.row%16
    def clear_channel(self):
        with self.core.lock:self.project.pattern[self.channel]=[Step() for _ in range(64)];self.capture_theme()
        self.status.set(f"CLEARED {CHANNEL_NAMES[self.channel]} // NEW PRIMARY THEME")
    def audition(self):
        note=self.project.pattern[self.channel][self.row].note or 12*(self.octave+1);self.core.audition(self.channel,note)
    def enter_note(self,ch):
        note=12*(self.octave+1)+NOTE_OFFSETS[NOTE_KEYS.index(ch)]
        if self.channel in DRUM_CHANNELS:note=(36,37,38,39,42,46,56)[min(6,NOTE_KEYS.index(ch)//2)]
        with self.core.lock:
            self.project.pattern[self.channel][self.row]=Step(note,13,"HIT" if self.channel in DRUM_CHANNELS else "MIN" if self.channel==2 else "---");self.capture_theme()
        self.core.audition(self.channel,note);self.row=(self.row+1)%64;self.page=self.row//16
    def erase_step(self):
        with self.core.lock:
            self.project.pattern[self.channel][self.row]=Step();self.capture_theme()
        self.status.set("STEP ERASED // NEW PRIMARY THEME")
    def click_tracker(self,e):
        if self.view_mode=="deck":
            w=max(2,self.tracker.winfo_width());h=max(2,self.tracker.winfo_height());gap=6
            pw=(w-gap)/2;ph=(h-gap)/2;column=0 if e.x<pw else 1;panel_row=0 if e.y<ph else 1
            self.page=panel_row*2+column;local_x=e.x-column*(pw+gap);local_y=e.y-panel_row*(ph+gap)
            header=36;rh=(ph-header-4)/16;left=42;cw=(pw-left)/CHANNEL_COUNT
            self.row=self.page*16+max(0,min(15,int((local_y-header)/max(1,rh))))
            self.channel=max(0,min(CHANNEL_COUNT-1,int((local_x-left)/max(1,cw))));self.set_focus("music");return
        w=max(1,self.tracker.winfo_width());h=max(1,self.tracker.winfo_height());header=38;rh=(h-header-8)/16
        self.row=self.page*16+max(0,min(15,int((e.y-header)/max(1,rh))));self.channel=max(0,min(CHANNEL_COUNT-1,int((e.x-55)/max(1,(w-60)/CHANNEL_COUNT))));self.set_focus("music")
    def slot_path(self):return user_data_root()/"states"/f"state_{max(0,min(9,int(self.state_slot.get())))}.json"
    def save_state(self):
        target=self.slot_path()
        try:self.project.save(target);self.status.set(f"STATE {self.state_slot.get()} SAVED")
        except Exception as exc:messagebox.showerror("Save failed",str(exc))
    def load_state(self):
        target=self.slot_path()
        if not target.exists():messagebox.showinfo("Empty state",f"State {self.state_slot.get()} is empty.");return
        self.smooth_change(lambda:self._load_state_now(target),f"LOAD STATE {self.state_slot.get()}")
    def _load_state_now(self,target):
        was=self.core.playing
        try:
            loaded=TrackerProject.load(target);self.core.stop();self.project=loaded;self.core.attach_project(loaded)
            self.style_index=next((i for i,s in enumerate(STYLES) if s["name"]==loaded.style),0)
            self.bpm.set(loaded.bpm);self.swing.set(loaded.swing);self.row=self.page=self.channel=0
            self.randomness.set(loaded.randomness*100);self.harmonic_motion.set(loaded.harmonic_motion*100)
            self.blend_target.set(loaded.blend_style or "NO BLEND");self.blend_amount.set(loaded.blend_amount*100);self.track_count.set(loaded.track_count)
            self.path_hold=not loaded.song_path_enabled
            self.capture_theme();self.vis.match_style(loaded.style)
            if was:self.core.start(0)
            self.auto_last_cycle=self.core.completed_cycles
            self.status.set(f"STATE {self.state_slot.get()} LOADED")
        except Exception as exc:messagebox.showerror("Load failed",str(exc))
    def export(self):
        target=filedialog.asksaveasfilename(title="Export CHIPFORGE WAV",initialdir=str(user_data_root()/"exports"),
            initialfile=f"{self.project.title.lower().replace(' ','_')}.wav",defaultextension=".wav",filetypes=(("WAV audio","*.wav"),))
        if not target:return
        was=self.core.playing;self.core.stop();self.status.set("RENDERING WAV...");self.root.update_idletasks()
        try:write_wav(Path(target),render_project(self.project,self.core.sample_rate),self.core.sample_rate);self.status.set(f"WAV READY: {Path(target).name}")
        except Exception as exc:messagebox.showerror("Export failed",str(exc))
        if was:self.core.start(0);self.auto_last_cycle=self.core.completed_cycles
    def open_forge(self):
        win=tk.Toplevel(self.root,bg=BG);self.apply_window_icon(win);win.title("WAVEFORM FORGE");win.geometry("620x760");inst=self.project.instruments[self.channel]
        vars={"wave":tk.StringVar(value=inst.waveform),"color":tk.DoubleVar(value=inst.color),"pulse":tk.DoubleVar(value=inst.pulse),"attack":tk.DoubleVar(value=inst.attack),"decay":tk.DoubleVar(value=inst.decay),"detune":tk.DoubleVar(value=inst.detune),"wobble":tk.DoubleVar(value=inst.wobble),"drive":tk.DoubleVar(value=inst.drive),"sub":tk.DoubleVar(value=inst.sub),"cutoff":tk.DoubleVar(value=inst.cutoff),"warmth":tk.DoubleVar(value=inst.warmth),"boom":tk.DoubleVar(value=inst.boom),"dust":tk.DoubleVar(value=inst.dust)}
        canvas=tk.Canvas(win,bg=BG,height=150,highlightbackground=GRID,highlightthickness=1);canvas.pack(fill="x",padx=14,pady=14)
        def apply(*_):
            inst.waveform=vars["wave"].get();inst.color=vars["color"].get();inst.pulse=vars["pulse"].get();inst.attack=vars["attack"].get();inst.decay=vars["decay"].get();inst.detune=vars["detune"].get();inst.wobble=vars["wobble"].get();inst.drive=vars["drive"].get();inst.sub=vars["sub"].get();inst.cutoff=vars["cutoff"].get();inst.warmth=vars["warmth"].get();inst.boom=vars["boom"].get();inst.dust=vars["dust"].get();draw()
        def draw():
            canvas.delete("all");v=self.core.preview_waveform(self.channel,256);w=max(10,canvas.winfo_width());h=max(10,canvas.winfo_height());pts=[]
            for i,x in enumerate(v):pts.extend((i*w/255,h/2-float(x)*h*.4))
            canvas.create_line(*pts,fill=CYAN,width=2)
        row=tk.Frame(win,bg=BG);row.pack(fill="x",padx=14);tk.Label(row,text="WAVEFORM",fg=WHITE,bg=BG).pack(side="left")
        ttk.Combobox(row,textvariable=vars["wave"],values=WAVEFORMS,state="readonly").pack(side="right",fill="x",expand=True);vars["wave"].trace_add("write",apply)
        for name,lo,hi,res in (("color",0,1,.01),("pulse",.05,.95,.01),("attack",.001,.2,.001),("decay",.05,3,.01),("detune",-.3,.3,.01),("wobble",0,1,.01),("drive",0,1,.01),("sub",0,.75,.01),("cutoff",200,12000,25),("warmth",0,1,.01),("boom",0,1,.01),("dust",0,1,.01)):
            f=tk.Frame(win,bg=BG);f.pack(fill="x",padx=14);tk.Label(f,text=name.upper(),fg=MUTED,bg=BG,width=9,anchor="w").pack(side="left")
            tk.Scale(f,from_=lo,to=hi,resolution=res,orient="horizontal",variable=vars[name],command=apply,bg=BG,fg=WHITE,troughcolor=GRID,highlightthickness=0).pack(side="right",fill="x",expand=True)
        buttons=tk.Frame(win,bg=BG);buttons.pack(fill="x",padx=14,pady=10)
        self.button(buttons,"AUDITION",lambda:self.audition(),LIME,"speaker").pack(side="left")
        def forge():
            vars["wave"].set(random.choice(WAVEFORMS));vars["color"].set(random.uniform(.15,.7));vars["pulse"].set(random.uniform(.25,.75));vars["attack"].set(random.uniform(.004,.08));vars["decay"].set(random.uniform(.3,2.2));vars["wobble"].set(random.uniform(.05,.8));vars["drive"].set(random.uniform(.08,.55));vars["sub"].set(random.uniform(.12,.52));vars["cutoff"].set(random.uniform(700,4200));vars["warmth"].set(random.uniform(.52,.88));vars["boom"].set(random.uniform(.45,1));vars["dust"].set(random.uniform(.04,.24));apply();self.audition()
        self.button(buttons,"RANDOM FORGE",forge,PINK,"hammer").pack(side="left",padx=5);self.button(buttons,"DONE",win.destroy,WHITE,"clear").pack(side="right");win.after(100,draw)
    def help(self):
        messagebox.showinfo(
            "CHIPFORGE WORKSTATION CONTROLS",
            f"{self.GLOBAL_HOTKEYS}\n\n{self.MUSIC_HOTKEYS}\n\n{self.EDIT_HOTKEYS}\n\n{self.VISUAL_HOTKEYS}\n\n"
            "VIEW\nThe gold View button cycles Split, Deck, Visual and Soundboard. Deck shows all four pages in a 2x2 grid. "
            "F6 swaps Deck and Visual while either has taken over. Escape exits OS fullscreen first, then returns takeover to Split.\n\n"
            "FLOW LAB\nBounded randomness, Music Math, style blending and 4 Core / 6 Full arrangement.\n\n"
            "STYLES\nThe eight bank buttons are instant live shortcuts. ALL STYLES opens the complete thirty-six-style chooser.\n\n"
            "SONG MAP\nThe four cards show the harmonic journey. Cyan is playing, green is queued. Automatic Path moves land every four bars; CUE NEXT and RETURN HOME land on the next bar. LOOP SCENE pauses automatic moves.\n\n"
            "EVOLVE\nEvolve changes drums, fills and melodic details inside the active scene. It does not choose the harmony; the Song Path does that.\n\n"
            "TRACK 7 SOUNDBOARD\nEight generated bass-vocal FX pads—not speech and not samples. Choose one to three curated vocal words: one is a stab, two is the default phrase, and three is a short chant. Cycle each visible word, add/remove the last slot, or randomize words independently. Manual pads quantize to the shared song clock. The sixteen cells are four bars of beat-sized loop memory. OFF keeps only live pads; LOOP repeats your fixed pattern; AUTO writes a new sparse one/two-hit loop at each Song Map scene without replacing your words. WOBBLE, DEEP and MUTANT carry sub-octave weight and tempo-locked filter motion. Press 7 to open the managed Soundboard takeover.\n\n"
            "The complete hotkey legend remains visible at the bottom of every view. In Insert mode the piano-row note keys take priority; press I to return to command mode."
        )
    def _next_vis(self):self.vis.cycle_scene(1)
    def _mutate_vis(self):self.vis.mutate()
    def _look(self):self.vis.cycle_look()
    def _fx(self):self.vis.cycle_fx()
    def _pixel(self):self.vis.pixel=not self.vis.pixel
    def _hud(self):self.vis.hud=not self.vis.hud
    def refresh(self):
        if self.song_path_event is not None:
            token,progression=self.song_path_event;self.song_path_event=None
            self.status.set(f"SONG MAP {self.project.song_path} // {self.scene_display_name(self.song_scene_index)} // {progression}")
        self.maybe_auto_mutate();self.update_auto_button()
        self.update_path_controls()
        if self.core.playing and self.view_mode!="deck":self.page=self.core.current_row//16
        self.bpm.set(self.project.bpm);self.swing.set(self.project.swing)
        blend=f" × {self.project.blend_style} {int(self.project.blend_amount*100)}%" if self.project.blend_style else ""
        self.meta.configure(text=f"{self.project.title}  //  {self.project.mode.upper()}  //  R{int(self.project.randomness*100)} H{int(self.project.harmonic_motion*100)}{blend}")
        if self.audio.error:self.status.set(self.audio.error)
        self.page_label.configure(text="ALL 4 PAGES // 2×2" if self.view_mode=="deck" else f"PAGE {self.page+1} / 4")
        for button in self.page_nav_buttons:button.configure(state="disabled" if self.view_mode=="deck" else "normal")
        self.tracks_btn.configure(text="6 FULL" if self.project.track_count>=6 else "4 CORE")
        self.flow_btn.configure(text=f"FLOW R{int(self.project.randomness*100)} H{int(self.project.harmonic_motion*100)}")
        self.update_vox_deck()
        self.draw_tracker();self.draw_meters();self.root.after(33,self.refresh)
    def draw_tracker(self):
        c=self.tracker;c.delete("all")
        if self.view_mode=="deck":self.draw_tracker_deck(c);return
        w=max(2,c.winfo_width());h=max(2,c.winfo_height());left=55;cw=(w-left)/CHANNEL_COUNT;header=38;rh=(h-header-8)/16
        for ch,name in enumerate(CHANNEL_NAMES):c.create_text(left+(ch+.5)*cw,16,text=f"{ch+1} {name}",fill=CYAN if ch==self.channel else MUTED,font=(MONO,10,"bold"))
        for i in range(17):c.create_line(0,header+i*rh,w,header+i*rh,fill=GRID)
        for ch in range(CHANNEL_COUNT+1):c.create_line(left+ch*cw,0,left+ch*cw,h,fill=GRID)
        play=self.core.current_row
        for i in range(16):
            row=self.page*16+i;y=header+(i+.5)*rh
            if row==play and self.core.playing:c.create_rectangle(0,header+i*rh,w,header+(i+1)*rh,fill="#102d29",outline="")
            if row==self.row:c.create_rectangle(0,header+i*rh,w,header+(i+1)*rh,outline=PINK,width=2)
            c.create_text(28,y,text=f"{row:02X}",fill=AMBER if row%4==0 else MUTED,font=(MONO,9))
            for ch in range(CHANNEL_COUNT):
                s=self.project.pattern[ch][row]
                text=(f"{midi_name(s.note):<4} {s.velocity:02X}" if cw<78 else f"{midi_name(s.note):<4} {s.velocity:02X} {s.effect:<3}") if s.note is not None else "---  --"
                c.create_text(left+ch*cw+8,y,anchor="w",text=text,fill=WHITE if s.note is not None else "#354958",font=(MONO,9))
    def draw_tracker_deck(self,c):
        w=max(2,c.winfo_width());h=max(2,c.winfo_height());gap=6;pw=(w-gap)/2;ph=(h-gap)/2;header=36;play=self.core.current_row
        for page in range(4):
            column=page%2;panel_row=page//2;x=column*(pw+gap);y=panel_row*(ph+gap);left=x+42;cw=(pw-42)/CHANNEL_COUNT;rh=(ph-header-4)/16
            font_size=8 if cw>=66 and rh>=14 else 7
            c.create_rectangle(x+1,y+1,x+pw-1,y+ph-1,outline=AMBER if page==self.page else GRID,width=2 if page==self.page else 1)
            c.create_text(x+7,y+8,anchor="nw",text=f"PAGE {page+1}  //  {page*16:02X}–{page*16+15:02X}",fill=AMBER,font=(MONO,8,"bold"))
            for ch,name in enumerate(CHANNEL_NAMES):
                c.create_text(left+(ch+.5)*cw,y+23,text=f"{ch+1} {name}",fill=CYAN if ch==self.channel else MUTED,font=(MONO,font_size,"bold"))
            for line in range(17):c.create_line(x,y+header+line*rh,x+pw,y+header+line*rh,fill=GRID)
            for ch in range(CHANNEL_COUNT+1):c.create_line(left+ch*cw,y+18,left+ch*cw,y+ph,fill=GRID)
            for index in range(16):
                row=page*16+index;cy=y+header+(index+.5)*rh
                if row==play and self.core.playing:c.create_rectangle(x+2,y+header+index*rh,x+pw-2,y+header+(index+1)*rh,fill="#102d29",outline="")
                if row==self.row:c.create_rectangle(x+1,y+header+index*rh,x+pw-1,y+header+(index+1)*rh,outline=PINK,width=2)
                c.create_text(x+20,cy,text=f"{row:02X}",fill=AMBER if row%4==0 else MUTED,font=(MONO,font_size))
                for ch in range(CHANNEL_COUNT):
                    step=self.project.pattern[ch][row]
                    text=(f"{midi_name(step.note):<4} {step.velocity:02X} {step.effect:<3}" if cw>=86 else f"{midi_name(step.note):<4} {step.velocity:02X}") if step.note is not None else "---  --"
                    c.create_text(left+ch*cw+4,cy,anchor="w",text=text,fill=WHITE if step.note is not None else "#354958",font=(MONO,font_size))
    def draw_meters(self):
        self.meters.delete("all")
        colors=(LIME,CYAN,AMBER,PINK,"#ff8a5b","#b967ff",WHITE)
        for i,v in enumerate(self.core.activity_levels()):
            x=i*31;self.meters.create_rectangle(x+2,4,x+29,25,outline=GRID);self.meters.create_rectangle(x+3,5,x+3+25*v,24,fill=colors[i],outline="")
    def close(self):
        # Recovery save is always the stable default, even when Save As points
        # at a named composition elsewhere.
        try:self.project.save(self.args.project)
        except Exception:pass
        self.audio.close();self.root.destroy()
    def run(self):self.set_focus("music");self.root.mainloop()


def parser():
    data=user_data_root()
    p=argparse.ArgumentParser(description="Integrated PipeWire-native CHIPFORGE visual workstation")
    p.add_argument("--project",type=Path,default=data/"projects"/"last_project.json");p.add_argument("--exports",type=Path,default=data/"exports")
    p.add_argument("--sample-rate",type=int,default=44100);p.add_argument("--geometry",default="1500x850");p.add_argument("--no-audio",action="store_true")
    p.add_argument("--render",action="store_true",help="export master, stems, MIDI and JSON without opening the GUI")
    p.add_argument("--doctor",action="store_true",help="check the graphical and PipeWire runtime")
    p.add_argument("--legacy",action="store_true",help="open the original terminal interface")
    return p


def main():
    args=parser().parse_args()
    if args.doctor:
        print(f"OK      NumPy               {np.__version__}")
        print(f"OK      Tk                  {tk.TkVersion}")
        bundled=Path(__file__).resolve().parent/"chipforge-pw-sink"
        pipewire=str(bundled) if bundled.is_file() else shutil.which("pw-cat")
        print(f"{'OK' if pipewire else 'ERROR'}   PipeWire bridge     {pipewire or 'not found'}")
        print("Signal path: tracker -> CHIPFORGE DSP -> signed stereo PCM -> PipeWire + visualizer")
        return 0 if pipewire or args.no_audio else 1
    if args.render:
        project=TrackerProject.load(args.project) if args.project.exists() else TrackerProject()
        if not args.project.exists():generate_song(project,0)
        print(export_project(project,args.exports,args.sample_rate));return 0
    if args.legacy:
        from chipforge_st import main as legacy_main
        legacy=[]
        if args.no_audio:legacy.append("--no-audio")
        return legacy_main(legacy)
    try:Workstation(args).run();return 0
    except (RuntimeError,tk.TclError) as exc:print(f"error: {exc}");return 1


if __name__=="__main__":raise SystemExit(main())
