#!/usr/bin/env python3
"""CHIPFORGE ST — a six-lane terminal tracker and raw-PCM synthesizer.

The sound path is intentionally small: tracker rows drive six custom software
voices, NumPy produces stereo PCM, and sounddevice sends signed 16-bit frames
to PortAudio/ALSA. No samples, DAW, browser, or model download are required.
"""

from __future__ import annotations

import argparse
import curses
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import random
import struct
import sys
import threading
import time
from typing import Any, Sequence
import wave

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - friendly startup failure
    raise SystemExit("CHIPFORGE ST needs NumPy: python -m pip install -r requirements.txt") from exc


APP = "CHIPFORGE ST"
VERSION = "1.3.0"
CHANNEL_NAMES = ("DRUM", "BASS", "CHORD", "LEAD", "PERC", "AIR")
CHANNEL_COUNT = len(CHANNEL_NAMES)
DRUM_CHANNELS = frozenset((0, 4))
WAVEFORMS = ("SINE", "SQUARE", "SAW", "TRIANGLE", "PULSE", "ORGAN", "FM", "RING", "METAL", "NOISE",
             "WOBBLE", "REESE", "LIQUID", "GROWL", "BUBBLE", "ROUND", "VELVET", "RUBBER", "DUBSUB", "HOLLOW",
             "808 SUB", "808 TAPE", "BOOM BAP", "DUSTY KEYS", "LOWRIDER", "VHS PAD", "CASSETTE KEYS",
             "TAPE FLUTE", "MALL BASS")
NOTE_KEYS = "zsxdcvgbhnjm,"  # chromatic C..C, familiar tracker layout
NOTE_OFFSETS = tuple(range(13))
BLOCKS = " ▁▂▃▄▅▆▇█"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def midi_name(note: int | None) -> str:
    if note is None:
        return "---"
    names = ("C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-")
    return f"{names[note % 12]}{note // 12 - 1}"


def note_frequency(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def variable_length(value: int) -> bytes:
    buffer = value & 0x7F
    output = bytearray()
    while value >> 7:
        value >>= 7
        buffer <<= 8
        buffer |= (value & 0x7F) | 0x80
    while True:
        output.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(output)


@dataclass
class Step:
    note: int | None = None
    velocity: int = 12
    effect: str = "..."


@dataclass
class Instrument:
    name: str
    waveform: str
    volume: float
    pan: float
    attack: float
    decay: float
    pulse: float = 0.50
    color: float = 0.50
    detune: float = 0.0
    wobble: float = 0.0
    drive: float = 0.0
    sub: float = 0.0
    cutoff: float = 4200.0
    warmth: float = 0.30
    boom: float = 0.0
    dust: float = 0.0


@dataclass
class TrackerProject:
    title: str = "UNTITLED CIRCUIT"
    style: str = "NEON NOIR"
    bpm: int = 118
    swing: float = 0.06
    rows: int = 64
    root: int = 40  # E2
    mode: str = "minor"
    seed: int = 808
    randomness: float = 0.46
    harmonic_motion: float = 0.65
    blend_style: str = ""
    blend_amount: float = 0.0
    track_count: int = 4
    progression: str = "i - VI - III - VII"
    instruments: list[Instrument] = field(default_factory=list)
    pattern: list[list[Step]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.instruments:
            self.instruments = default_instruments()
        if not self.pattern:
            self.pattern = [[Step() for _ in range(self.rows)] for _ in range(CHANNEL_COUNT)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 2,
            "app": APP,
            "version": VERSION,
            "title": self.title,
            "style": self.style,
            "bpm": self.bpm,
            "swing": self.swing,
            "rows": self.rows,
            "root": self.root,
            "mode": self.mode,
            "seed": self.seed,
            "randomness": self.randomness,
            "harmonic_motion": self.harmonic_motion,
            "blend_style": self.blend_style,
            "blend_amount": self.blend_amount,
            "track_count": self.track_count,
            "progression": self.progression,
            "instruments": [asdict(item) for item in self.instruments],
            "pattern": [[asdict(step) for step in channel] for channel in self.pattern],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrackerProject":
        rows = int(data.get("rows", 64))
        instruments = [Instrument(**item) for item in data.get("instruments", [])]
        raw_pattern = data.get("pattern", [])
        pattern = [[Step(**step) for step in channel] for channel in raw_pattern]
        source_channels = len(pattern) if pattern else len(instruments)
        if source_channels == 4:
            defaults = default_instruments()
            instruments.extend(defaults[len(instruments):CHANNEL_COUNT])
            pattern.extend([[Step() for _ in range(rows)] for _ in range(CHANNEL_COUNT - len(pattern))])
        project = cls(
            title=str(data.get("title", "UNTITLED CIRCUIT")),
            style=str(data.get("style", "NEON NOIR")),
            bpm=int(data.get("bpm", 118)),
            swing=float(data.get("swing", 0.06)),
            rows=rows,
            root=int(data.get("root", 40)),
            mode=str(data.get("mode", "minor")),
            seed=int(data.get("seed", 808)),
            randomness=clamp(float(data.get("randomness", 0.46)), 0.0, 1.0),
            harmonic_motion=clamp(float(data.get("harmonic_motion", 0.65)), 0.0, 1.0),
            blend_style=str(data.get("blend_style", "")),
            blend_amount=clamp(float(data.get("blend_amount", 0.0)), 0.0, 1.0),
            track_count=6 if int(data.get("track_count", source_channels or 4)) >= 6 else 4,
            progression=str(data.get("progression", "i - VI - III - VII")),
            instruments=instruments,
            pattern=pattern,
        )
        if len(project.instruments) != CHANNEL_COUNT or len(project.pattern) != CHANNEL_COUNT:
            raise ValueError(f"project must contain four legacy channels or {CHANNEL_COUNT} current channels")
        if any(len(channel) != rows for channel in project.pattern):
            raise ValueError("pattern channel length does not match rows")
        return project

    def clone(self) -> "TrackerProject":
        return TrackerProject.from_dict(self.to_dict())

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "TrackerProject":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def default_instruments() -> list[Instrument]:
    return [
        Instrument("ROUND 808 KIT", "NOISE", 0.72, -0.08, 0.002, 0.58, color=0.42, cutoff=6200, warmth=.55, boom=.68, dust=.14),
        Instrument("FAT COPPER", "ROUND", 0.42, -0.22, 0.009, 0.72, color=0.32, sub=.30, cutoff=1450, warmth=.70, dust=.05),
        Instrument("VELVET CHORD", "VELVET", 0.20, 0.14, 0.035, 1.25, color=0.40, detune=0.05, cutoff=2800, warmth=.62, dust=.08),
        Instrument("RUBBER LEAD", "RUBBER", 0.22, 0.28, 0.012, 0.58, color=0.40, cutoff=3400, warmth=.58, dust=.07),
        Instrument("POCKET PERC", "NOISE", 0.15, 0.36, 0.002, 0.32, color=0.32, cutoff=4600, warmth=.72, dust=.12),
        Instrument("AIR MEMORY", "HOLLOW", 0.10, -0.34, 0.075, 1.85, color=0.38, detune=-0.04, cutoff=1900, warmth=.82, dust=.10),
    ]


SCALE_MODES: dict[str, tuple[int, ...]] = {
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "harmonic minor": (0, 2, 3, 5, 7, 8, 11),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
}

PROGRESSIONS: tuple[tuple[str, tuple[int, int, int, int], float], ...] = (
    ("i - VI - III - VII", (0, 5, 2, 6), .42),
    ("i - iv - VI - V", (0, 3, 5, 4), .70),
    ("i - VII - VI - VII", (0, 6, 5, 6), .34),
    ("i - III - VII - iv", (0, 2, 6, 3), .56),
    ("i - VI - iv - V", (0, 5, 3, 4), .78),
    ("i - iv - i - V", (0, 3, 0, 4), .62),
    ("i - i - VI - i", (0, 0, 5, 0), .16),
)


def chord_intervals(effect: str) -> tuple[int, ...]:
    """Decode the compact tracker chord tag for live audio and MIDI alike."""
    return {
        "MAJ": (0, 4, 7),
        "MIN": (0, 3, 7),
        "DIM": (0, 3, 6),
        "AUG": (0, 4, 8),
        "SUS": (0, 5, 7),
        "M7": (0, 4, 7, 11),
        "m7": (0, 3, 7, 10),
        "7TH": (0, 4, 7, 10),
    }.get(effect, (0, 3, 7))


def diatonic_quality(scale: Sequence[int], degree: int, seventh: bool = False) -> str:
    """Return the chord quality created by stacking scale thirds."""
    root = scale[degree]
    third_index, fifth_index = degree + 2, degree + 4
    third = scale[third_index % 7] + 12 * (third_index // 7) - root
    fifth = scale[fifth_index % 7] + 12 * (fifth_index // 7) - root
    if seventh:
        seventh_index = degree + 6
        seventh_interval = scale[seventh_index % 7] + 12 * (seventh_index // 7) - root
        if (third, fifth, seventh_interval) == (4, 7, 11):
            return "M7"
        if (third, fifth, seventh_interval) == (3, 7, 10):
            return "m7"
        if (third, fifth, seventh_interval) == (4, 7, 10):
            return "7TH"
    if (third, fifth) == (4, 7):
        return "MAJ"
    if (third, fifth) == (3, 6):
        return "DIM"
    if (third, fifth) == (4, 8):
        return "AUG"
    return "MIN"


STYLES: tuple[dict[str, Any], ...] = (
    {"name": "NEON NOIR", "bpm": 118, "root": 40, "swing": 0.06, "density": 0.54, "waves": ("NOISE", "SAW", "ORGAN", "FM")},
    {"name": "DESERT DRIVE", "bpm": 108, "root": 40, "swing": 0.02, "density": 0.45, "waves": ("NOISE", "SQUARE", "PULSE", "RING")},
    {"name": "CATHEDRAL CIRCUIT", "bpm": 92, "root": 38, "swing": 0.08, "density": 0.36, "waves": ("NOISE", "TRIANGLE", "ORGAN", "METAL")},
    {"name": "ARCADE PANIC", "bpm": 148, "root": 36, "swing": 0.00, "density": 0.76, "waves": ("NOISE", "PULSE", "SQUARE", "FM")},
    {"name": "MIDNIGHT FUNK", "bpm": 104, "root": 41, "swing": 0.14, "density": 0.60, "waves": ("NOISE", "SAW", "PULSE", "SINE")},
    {"name": "SWAMP CIRCUIT", "bpm": 140, "root": 34, "swing": 0.12, "density": 0.48, "waves": ("NOISE", "WOBBLE", "LIQUID", "GROWL")},
    {"name": "MUTANT MARSH", "bpm": 150, "root": 33, "swing": 0.08, "density": 0.56, "waves": ("NOISE", "REESE", "ORGAN", "BUBBLE")},
    {"name": "COSMIC SLUDGE", "bpm": 130, "root": 35, "swing": 0.16, "density": 0.42, "waves": ("NOISE", "GROWL", "LIQUID", "FM")},
    {"name": "808 BOOM BAP", "bpm": 92, "root": 31, "swing": 0.12, "density": 0.52, "waves": ("NOISE", "808 SUB", "DUSTY KEYS", "808 TAPE")},
    {"name": "TRUNK RATTLE", "bpm": 74, "root": 29, "swing": 0.09, "density": 0.46, "waves": ("NOISE", "LOWRIDER", "VELVET", "BOOM BAP")},
    {"name": "GOLDEN ERA DUST", "bpm": 94, "root": 33, "swing": 0.15, "density": 0.58, "waves": ("NOISE", "BOOM BAP", "DUSTY KEYS", "HOLLOW")},
    {"name": "SOUTH SIDE 808", "bpm": 140, "root": 28, "swing": 0.05, "density": 0.66, "waves": ("NOISE", "808 TAPE", "VELVET", "RUBBER")},
    {"name": "NIGHT BUS BASS", "bpm": 82, "root": 30, "swing": 0.18, "density": 0.42, "waves": ("NOISE", "LOWRIDER", "DUSTY KEYS", "808 SUB")},
    {"name": "CRATE DIGGER", "bpm": 96, "root": 32, "swing": 0.14, "density": 0.55, "waves": ("NOISE", "BOOM BAP", "DUSTY KEYS", "HOLLOW")},
    {"name": "MEMPHIS TAPE", "bpm": 72, "root": 30, "swing": 0.10, "density": 0.50, "waves": ("NOISE", "808 TAPE", "DUSTY KEYS", "BOOM BAP")},
    {"name": "LOWRIDER SUNSET", "bpm": 88, "root": 32, "swing": 0.13, "density": 0.47, "waves": ("NOISE", "LOWRIDER", "VELVET", "808 TAPE")},
    {"name": "MALL AFTER MIDNIGHT", "bpm": 72, "root": 36, "swing": 0.10, "density": 0.34, "waves": ("NOISE", "MALL BASS", "VHS PAD", "TAPE FLUTE")},
    {"name": "VHS PALMS", "bpm": 78, "root": 33, "swing": 0.12, "density": 0.40, "waves": ("NOISE", "MALL BASS", "CASSETTE KEYS", "TAPE FLUTE")},
    {"name": "PLAZA ELEVATOR", "bpm": 84, "root": 38, "swing": 0.07, "density": 0.36, "waves": ("NOISE", "LOWRIDER", "VHS PAD", "CASSETTE KEYS")},
    {"name": "EMPTY FOOD COURT", "bpm": 66, "root": 35, "swing": 0.14, "density": 0.30, "waves": ("NOISE", "808 TAPE", "VHS PAD", "HOLLOW")},
    {"name": "WINDOWS 95 SUNSET", "bpm": 88, "root": 40, "swing": 0.08, "density": 0.44, "waves": ("NOISE", "MALL BASS", "CASSETTE KEYS", "VHS PAD")},
    {"name": "NEON AQUARIUM", "bpm": 92, "root": 41, "swing": 0.10, "density": 0.46, "waves": ("NOISE", "DUBSUB", "VHS PAD", "TAPE FLUTE")},
    {"name": "RAINY WINDOW BEATS", "bpm": 78, "root": 33, "swing": 0.22, "density": 0.44, "waves": ("NOISE", "808 SUB", "CASSETTE KEYS", "TAPE FLUTE")},
    {"name": "STUDY TAPE 1998", "bpm": 84, "root": 36, "swing": 0.18, "density": 0.50, "waves": ("NOISE", "BOOM BAP", "DUSTY KEYS", "HOLLOW")},
    {"name": "BEDROOM CASSETTE", "bpm": 72, "root": 38, "swing": 0.24, "density": 0.38, "waves": ("NOISE", "808 TAPE", "CASSETTE KEYS", "TAPE FLUTE")},
    {"name": "SUNDAY VINYL", "bpm": 86, "root": 41, "swing": 0.17, "density": 0.47, "waves": ("NOISE", "LOWRIDER", "DUSTY KEYS", "HOLLOW")},
    {"name": "LATE NIGHT HOMEWORK", "bpm": 80, "root": 35, "swing": 0.21, "density": 0.42, "waves": ("NOISE", "MALL BASS", "CASSETTE KEYS", "HOLLOW")},
    {"name": "COFFEE SHOP LOOP", "bpm": 90, "root": 40, "swing": 0.19, "density": 0.48, "waves": ("NOISE", "BOOM BAP", "CASSETTE KEYS", "TAPE FLUTE")},
)

HIPHOP_STYLE_NAMES = frozenset({"808 BOOM BAP", "TRUNK RATTLE", "GOLDEN ERA DUST", "SOUTH SIDE 808",
                                "NIGHT BUS BASS", "CRATE DIGGER", "MEMPHIS TAPE", "LOWRIDER SUNSET"})
VAPORWAVE_STYLE_NAMES = frozenset({"MALL AFTER MIDNIGHT", "VHS PALMS", "PLAZA ELEVATOR", "EMPTY FOOD COURT",
                                   "WINDOWS 95 SUNSET", "NEON AQUARIUM"})
LOFI_STYLE_NAMES = frozenset({"RAINY WINDOW BEATS", "STUDY TAPE 1998", "BEDROOM CASSETTE", "SUNDAY VINYL",
                              "LATE NIGHT HOMEWORK", "COFFEE SHOP LOOP"})


def generate_song(
    project: TrackerProject,
    style_index: int,
    seed: int | None = None,
    randomness: float | None = None,
    harmonic_motion: float | None = None,
    blend_style_index: int | None = None,
    blend_amount: float | None = None,
    track_count: int | None = None,
) -> None:
    """Generate a four-bar arrangement with bounded style and theory controls.

    Randomness changes rhythm, voicing and motif treatment; it never releases
    notes from the active scale. Harmonic motion selects a progression by its
    amount of functional travel. A style blend interpolates tempo, swing,
    density, key center and voice families while retaining one coherent song.
    """
    base_style = STYLES[style_index % len(STYLES)]
    project.randomness = clamp(project.randomness if randomness is None else randomness, 0.0, 1.0)
    project.harmonic_motion = clamp(project.harmonic_motion if harmonic_motion is None else harmonic_motion, 0.0, 1.0)
    project.blend_amount = clamp(project.blend_amount if blend_amount is None else blend_amount, 0.0, 1.0)
    project.track_count = 6 if (project.track_count if track_count is None else track_count) >= 6 else 4
    if blend_style_index is None and project.blend_style:
        blend_style_index = next((i for i, item in enumerate(STYLES) if item["name"] == project.blend_style), None)
    target_style = STYLES[blend_style_index % len(STYLES)] if blend_style_index is not None else base_style
    if target_style["name"] == base_style["name"]:
        project.blend_amount = 0.0
    blend = project.blend_amount
    project.style = base_style["name"]
    project.blend_style = target_style["name"] if blend > 0.0 else ""
    project.seed = int(seed if seed is not None else random.randint(1, 2**31 - 1))
    rng = random.Random(project.seed)
    lerp = lambda a, b: a + (b - a) * blend
    rhythm_style = target_style if blend >= .5 else base_style
    waves = tuple(
        target_style["waves"][channel] if blend > 0.0 and rng.random() < blend else base_style["waves"][channel]
        for channel in range(4)
    )
    style = dict(rhythm_style)
    style["bpm"] = int(round(lerp(float(base_style["bpm"]), float(target_style["bpm"]))))
    style["root"] = int(round(lerp(float(base_style["root"]), float(target_style["root"]))))
    style["swing"] = lerp(float(base_style["swing"]), float(target_style["swing"]))
    raw_density = lerp(float(base_style["density"]), float(target_style["density"]))
    density = clamp(raw_density * (.72 + project.randomness * .56), .16, .88)
    style["density"] = density
    style["waves"] = waves
    project.bpm = int(style["bpm"])
    project.root = int(style["root"])
    project.swing = float(style["swing"])
    vaporwave = style["name"] in VAPORWAVE_STYLE_NAMES
    lofi = style["name"] in LOFI_STYLE_NAMES
    suffixes = (("MEMORY", "PLAZA", "SUNSET", "DREAM") if vaporwave else
                ("LOOP", "SIDE A", "NOTEBOOK", "RAIN") if lofi else
                ("TRANSMISSION", "MACHINE", "SIGNAL", "RITUAL"))
    blend_title = f" × {target_style['name']}" if blend > 0 else ""
    project.title = f"{base_style['name']}{blend_title} {rng.choice(suffixes)}"
    project.pattern = [[Step() for _ in range(project.rows)] for _ in range(CHANNEL_COUNT)]
    hiphop = style["name"] in HIPHOP_STYLE_NAMES
    for channel, (instrument, waveform) in enumerate(zip(project.instruments[:4], style["waves"])):
        # A preset is a complete voice design. Reset the structural controls so
        # a slow VHS pad cannot leak its envelope or level into a later
        # chiptune/808 selection when users jump between banks.
        base_voice = (
            ("ROUND 808 KIT", .72, -.08, .002, .58),
            ("FAT COPPER", .42, -.22, .009, .72),
            ("VELVET CHORD", .20, .14, .035, 1.25),
            ("RUBBER LEAD", .22, .28, .012, .58),
        )[channel]
        instrument.name, instrument.volume, instrument.pan, instrument.attack, instrument.decay = base_voice
        instrument.waveform = waveform
        instrument.color = rng.uniform(0.28, 0.82)
        instrument.pulse = rng.uniform(0.24, 0.76)
        instrument.detune = rng.uniform(-0.12, 0.12)
        wonky = style["name"] in ("SWAMP CIRCUIT", "MUTANT MARSH", "COSMIC SLUDGE")
        instrument.wobble = rng.uniform(0.35, 0.95) if wonky else rng.uniform(0.0, 0.18)
        instrument.drive = rng.uniform(0.28, 0.78) if wonky else rng.uniform(0.0, 0.15)
        instrument.sub = (rng.uniform(.25, .48) if wonky else rng.uniform(.16, .32)) if channel == 1 else 0.0
        # Generated patches are deliberately voiced dark and broad. Users can
        # open them up in Waveform Forge, but generation never defaults to icepick highs.
        ranges = ((4600, 7200), (720, 1900), (1500, 3500), (1900, 4400))
        instrument.cutoff = rng.uniform(*ranges[channel])
        instrument.warmth = rng.uniform(.48, .78 if wonky else .68)
        instrument.dust = rng.uniform(.05, .18) if channel == 0 else rng.uniform(.025, .11)
        instrument.boom = rng.uniform(.48, .72) if channel == 0 else 0.0

        # Hip-hop machines are genuinely revoiced, not aliases for the old
        # presets: long pitched kick tails, sub-first bass and deliberately
        # dark, slightly worn upper voices.
        if hiphop:
            instrument.warmth = rng.uniform(.62, .90)
            instrument.dust = rng.uniform(.09, .28) if channel in (0, 2) else rng.uniform(.04, .16)
            if channel == 0:
                instrument.name = "CRATE 808 KIT"
                instrument.volume = rng.uniform(.72, .82)
                instrument.decay = rng.uniform(.65, 1.05)
                instrument.cutoff = rng.uniform(4200, 6200)
                instrument.boom = rng.uniform(.78, 1.0)
            elif channel == 1:
                instrument.name = rng.choice(("TRUNK 808", "LOW END THEORY", "SUBWAY SUB"))
                instrument.volume = rng.uniform(.42, .50)
                instrument.attack = rng.uniform(.002, .012)
                instrument.decay = rng.uniform(1.0, 2.25)
                instrument.sub = rng.uniform(.34, .56)
                instrument.drive = rng.uniform(.12, .38)
                instrument.cutoff = rng.uniform(620, 1350)
            elif channel == 2:
                instrument.name = rng.choice(("DUSTY KEYS", "MILK CRATE CHORD", "TAPE DECK KEYS"))
                instrument.cutoff = rng.uniform(1200, 2600)
                instrument.drive = rng.uniform(.06, .24)
            else:
                instrument.name = rng.choice(("DIRTY HOOK", "CASSETTE LEAD", "CORNER STORE LEAD"))
                instrument.cutoff = rng.uniform(1500, 3300)
                instrument.drive = rng.uniform(.10, .32)

        # Vaporwave gets slow, blurred envelopes and a heavily softened VHS
        # signal path. Lo-fi beats use shorter dusty keys and a swung sampler-
        # like rhythm section. Both remain fully synthesized and sample-free.
        elif vaporwave:
            instrument.warmth = rng.uniform(.78, .98)
            instrument.dust = rng.uniform(.12, .30)
            if channel == 0:
                instrument.name = rng.choice(("VHS DRUM MACHINE", "MALL ATRIUM KIT", "SUNSET KIT"))
                instrument.volume = rng.uniform(.60, .72)
                instrument.decay = rng.uniform(.48, .82)
                instrument.cutoff = rng.uniform(3000, 4900)
                instrument.boom = rng.uniform(.54, .78)
            elif channel == 1:
                instrument.name = rng.choice(("MALL BASS", "VHS LOW END", "PLAZA SUB"))
                instrument.volume = rng.uniform(.34, .43)
                instrument.attack = rng.uniform(.012, .045)
                instrument.decay = rng.uniform(1.55, 2.80)
                instrument.detune = rng.uniform(-.08, .04)
                instrument.sub = rng.uniform(.24, .40)
                instrument.drive = rng.uniform(.04, .16)
                instrument.cutoff = rng.uniform(520, 1120)
            elif channel == 2:
                instrument.name = rng.choice(("VHS DREAM PAD", "EMPTY MALL KEYS", "ESCALATOR CHORD"))
                instrument.volume = rng.uniform(.17, .24)
                instrument.attack = rng.uniform(.10, .24)
                instrument.decay = rng.uniform(2.10, 3.40)
                instrument.detune = rng.uniform(.04, .14)
                instrument.wobble = rng.uniform(.025, .10)
                instrument.drive = rng.uniform(.04, .14)
                instrument.cutoff = rng.uniform(900, 2050)
            else:
                instrument.name = rng.choice(("TAPE FLUTE", "LOST SAX MEMORY", "AQUARIUM LEAD"))
                instrument.volume = rng.uniform(.14, .21)
                instrument.attack = rng.uniform(.045, .15)
                instrument.decay = rng.uniform(1.20, 2.50)
                instrument.detune = rng.uniform(-.10, .10)
                instrument.wobble = rng.uniform(.02, .09)
                instrument.cutoff = rng.uniform(1050, 2450)

        elif lofi:
            instrument.warmth = rng.uniform(.80, .98)
            instrument.dust = rng.uniform(.18, .38) if channel in (0, 2) else rng.uniform(.10, .27)
            if channel == 0:
                instrument.name = rng.choice(("DUSTY POCKET KIT", "BEDROOM DRUMS", "VINYL KIT"))
                instrument.volume = rng.uniform(.64, .76)
                instrument.decay = rng.uniform(.50, .88)
                instrument.cutoff = rng.uniform(2800, 4700)
                instrument.boom = rng.uniform(.60, .86)
            elif channel == 1:
                instrument.name = rng.choice(("STUDY SUB", "COFFEEHOUSE BASS", "BEDROOM 808"))
                instrument.volume = rng.uniform(.35, .44)
                instrument.attack = rng.uniform(.006, .025)
                instrument.decay = rng.uniform(.88, 1.70)
                instrument.sub = rng.uniform(.25, .43)
                instrument.drive = rng.uniform(.06, .20)
                instrument.cutoff = rng.uniform(500, 1080)
            elif channel == 2:
                instrument.name = rng.choice(("DUSTY SEVENTHS", "NOTEBOOK KEYS", "COFFEE SHOP KEYS"))
                instrument.volume = rng.uniform(.17, .24)
                instrument.attack = rng.uniform(.035, .095)
                instrument.decay = rng.uniform(1.20, 2.25)
                instrument.detune = rng.uniform(.025, .10)
                instrument.drive = rng.uniform(.04, .16)
                instrument.cutoff = rng.uniform(850, 1850)
            else:
                instrument.name = rng.choice(("RAINY LEAD", "TAPE HUM HOOK", "SLEEPY FLUTE"))
                instrument.volume = rng.uniform(.13, .20)
                instrument.attack = rng.uniform(.025, .10)
                instrument.decay = rng.uniform(.72, 1.55)
                instrument.detune = rng.uniform(-.08, .08)
                instrument.cutoff = rng.uniform(950, 2150)

    # The extra lanes are arrangement colors, deliberately quieter than the
    # four core voices. They can be switched off without changing core notes.
    perc, air = project.instruments[4], project.instruments[5]
    perc.name = "DUST POCKET" if lofi else "VHS PERC" if vaporwave else "SIDE PERC"
    perc.waveform = "NOISE"
    perc.volume = rng.uniform(.11, .17)
    perc.pan = rng.uniform(.26, .44)
    perc.attack, perc.decay = .002, rng.uniform(.22, .42)
    perc.cutoff = rng.uniform(2900, 4900)
    perc.warmth = rng.uniform(.66, .88)
    perc.dust = rng.uniform(.12, .30)
    perc.boom = rng.uniform(.08, .24)
    air.name = "MALL AIR" if vaporwave else "RAIN AIR" if lofi else "GHOST COUNTER"
    air.waveform = "VHS PAD" if vaporwave else "CASSETTE KEYS" if lofi else rng.choice(("HOLLOW", "VELVET", "TAPE FLUTE"))
    air.volume = rng.uniform(.075, .115)
    air.pan = rng.uniform(-.46, -.26)
    air.attack = rng.uniform(.055, .16)
    air.decay = rng.uniform(1.30, 2.70)
    air.detune = rng.uniform(-.08, .06)
    air.wobble = rng.uniform(.02, .12)
    air.drive = rng.uniform(.02, .10)
    air.sub = 0.0
    air.cutoff = rng.uniform(980, 2100)
    air.warmth = rng.uniform(.76, .94)
    air.dust = rng.uniform(.07, .20)
    air.boom = 0.0

    # One drum lane carries a compact General-MIDI-like kit: 36 kick, 38 snare, 42 hat.
    for row in range(project.rows):
        pos = row % 16
        note: int | None = None
        velocity = 10
        hiphop_kicks = {
            "808 BOOM BAP": (0, 7, 10), "TRUNK RATTLE": (0, 3, 10, 14),
            "GOLDEN ERA DUST": (0, 6, 10), "SOUTH SIDE 808": (0, 7, 10, 14),
            "NIGHT BUS BASS": (0, 6, 11), "CRATE DIGGER": (0, 6, 10, 13),
            "MEMPHIS TAPE": (0, 5, 10), "LOWRIDER SUNSET": (0, 7, 11),
        }
        vapor_kicks = {
            "MALL AFTER MIDNIGHT": (0, 10), "VHS PALMS": (0, 7, 11), "PLAZA ELEVATOR": (0, 10),
            "EMPTY FOOD COURT": (0, 11), "WINDOWS 95 SUNSET": (0, 6, 10), "NEON AQUARIUM": (0, 7, 12),
        }
        lofi_kicks = {
            "RAINY WINDOW BEATS": (0, 7, 10), "STUDY TAPE 1998": (0, 6, 11), "BEDROOM CASSETTE": (0, 7, 10),
            "SUNDAY VINYL": (0, 6, 10, 14), "LATE NIGHT HOMEWORK": (0, 7, 11), "COFFEE SHOP LOOP": (0, 6, 10),
        }
        if vaporwave and pos in vapor_kicks[style["name"]] and (pos == 0 or rng.random() < .72):
            note, velocity = 36, 11 + rng.randrange(4)
        elif lofi and pos in lofi_kicks[style["name"]] and (pos == 0 or rng.random() < .82):
            note, velocity = 36, 12 + rng.randrange(4)
        elif hiphop and pos in hiphop_kicks[style["name"]] and (pos == 0 or rng.random() < .86):
            note, velocity = 36, 13 + rng.randrange(3)
        elif pos in (0, 8) or (pos == 10 and rng.random() < density):
            note, velocity = 36, 15
        elif pos in (4, 12):
            note = 39 if hiphop and style["name"] in ("TRUNK RATTLE", "MEMPHIS TAPE", "SOUTH SIDE 808") else 38
            velocity = 11 + rng.randrange(3) if vaporwave else 12 + rng.randrange(3) if lofi else 14
        elif hiphop and style["name"] == "MEMPHIS TAPE" and pos in (3, 11) and rng.random() < .52:
            note, velocity = 56, 9 + rng.randrange(3)
        elif hiphop and pos == 14 and rng.random() < .42:
            note, velocity = 46, 7 + rng.randrange(3)
        elif vaporwave and pos % 4 == 2 and rng.random() < density + .20:
            note, velocity = 42, 6 + rng.randrange(3)
        elif lofi and (pos % 2 == 0 or rng.random() < density * .38):
            note, velocity = 42, 6 + rng.randrange(4)
        elif pos % 2 == 0 or rng.random() < density * (0.48 if hiphop else 0.30):
            note, velocity = 42, 8 + rng.randrange(4)
        if note is not None:
            project.pattern[0][row] = Step(note, velocity, "HIT")

    if hiphop and project.randomness > .72:
        project.mode = "phrygian"
    elif (vaporwave or lofi) and project.harmonic_motion > .48:
        project.mode = "dorian"
    elif project.harmonic_motion > .86:
        project.mode = "harmonic minor"
    else:
        project.mode = "aeolian"
    scale = SCALE_MODES[project.mode]
    ranked_progressions = sorted(PROGRESSIONS, key=lambda item: abs(item[2] - project.harmonic_motion))
    choice_depth = 1 + int(project.randomness * 3.99)
    progression_name, progression, _motion = rng.choice(ranked_progressions[:choice_depth])
    project.progression = progression_name
    previous_chord_root: int | None = None
    for bar in range(4):
        degree = progression[bar]
        root = project.root + scale[degree]
        bass_rows = (0, 8) if vaporwave else (0, 6, 10, 14) if lofi else (0, 6, 8, 12)
        for local_row in bass_rows:
            if local_row != 0 and rng.random() > density + 0.25:
                continue
            row = bar * 16 + local_row
            # Root, fifth and a scale pickup all belong to the current harmony.
            if local_row == 0:
                note = root
            elif local_row in (8, 12):
                note = root + 7
            else:
                pickup_degree = (degree + (1 if local_row >= 10 else -1)) % 7
                note = project.root + scale[pickup_degree]
            project.pattern[1][row] = Step(note, 11 + rng.randrange(4), "GLD")
        chord_velocity = 8 + rng.randrange(3) if vaporwave else 9 + rng.randrange(3) if lofi else 10 + rng.randrange(3)
        chord_root = root + 12
        if previous_chord_root is not None:
            chord_root = min((chord_root - 12, chord_root, chord_root + 12), key=lambda note: abs(note - previous_chord_root))
        previous_chord_root = chord_root
        quality = diatonic_quality(scale, degree, seventh=(vaporwave or lofi) and project.harmonic_motion > .52)
        project.pattern[2][bar * 16] = Step(chord_root, chord_velocity, quality)
        if rng.random() < density + (.18 if vaporwave else .08 if lofi else 0):
            project.pattern[2][bar * 16 + 8] = Step(chord_root, 7 + rng.randrange(3), quality)

    # Compose one small motif, then restate and transform it across the four
    # bars. Recognition survives while randomness still changes the answers.
    lead_grid = 4 if vaporwave else 2
    motif_slots = tuple(range(0, 16, lead_grid))
    motif: list[int | None] = []
    walk = rng.randrange(0, 3)
    for slot in motif_slots:
        if slot and rng.random() > density * (.72 if vaporwave else .86 if lofi else 1.0):
            motif.append(None)
            continue
        walk = max(0, min(6, walk + rng.choice((-1, 0, 1, 1, 2 if project.randomness > .66 else 1))))
        motif.append(walk)
    if all(item is None for item in motif):
        motif[0] = 0
    for bar in range(4):
        degree = progression[bar]
        transformed = list(motif)
        if bar == 2 and project.randomness > .54:
            transformed = list(reversed(transformed))
        for index, motif_degree in enumerate(transformed):
            if motif_degree is None:
                continue
            if bar and index and rng.random() < project.randomness * .16:
                motif_degree = max(0, min(6, motif_degree + rng.choice((-1, 1))))
            absolute_degree = degree + motif_degree
            octave_shift, scale_index = divmod(absolute_degree, 7)
            octave = (12 if vaporwave else 24) + octave_shift * 12
            note = project.root + octave + scale[scale_index]
            velocity = 6 + rng.randrange(5) if vaporwave or lofi else 8 + rng.randrange(7)
            project.pattern[3][bar * 16 + motif_slots[index]] = Step(note, velocity, "MOT")

    if project.track_count >= 6:
        # PERC answers the main drum lane only on unclaimed offbeats.
        perc_probability = .12 + density * (.22 + project.randomness * .24)
        for row in range(project.rows):
            pos = row % 16
            if pos in (0, 4, 8, 12) or project.pattern[0][row].note in (38, 39):
                continue
            if pos in (3, 6, 7, 10, 14, 15) and rng.random() < perc_probability:
                note = rng.choice((37, 42, 42, 46, 56 if hiphop else 39))
                project.pattern[4][row] = Step(note, 5 + rng.randrange(4), "PCK")
        # AIR is a sparse call-and-response lane tied to chord tones.
        for bar in range(4):
            degree = progression[bar]
            answer_row = bar * 16 + (12 if bar % 2 == 0 else 8)
            if rng.random() < .38 + project.harmonic_motion * .34:
                air_degree = degree + (4 if bar % 2 == 0 else 2)
                octave_shift, scale_index = divmod(air_degree, 7)
                note = project.root + 24 + octave_shift * 12 + scale[scale_index]
                project.pattern[5][answer_row] = Step(note, 5 + rng.randrange(3), "AIR")
        if not any(step.note is not None for step in project.pattern[4]):
            project.pattern[4][6] = Step(42, 6, "PCK")
        if not any(step.note is not None for step in project.pattern[5]):
            degree = progression[0] + 4
            octave_shift, scale_index = divmod(degree, 7)
            project.pattern[5][12] = Step(project.root + 24 + octave_shift * 12 + scale[scale_index], 6, "AIR")


def mutate_song(project: TrackerProject, amount: float = 0.14, seed: int | None = None) -> int:
    rng = random.Random(seed if seed is not None else random.randint(1, 2**31 - 1))
    scale = SCALE_MODES.get(project.mode, SCALE_MODES["aeolian"])
    changes = 0
    melodic_channels = (1, 2, 3, 5) if project.track_count >= 6 else (1, 2, 3)
    for channel in melodic_channels:
        for row, step in enumerate(project.pattern[channel]):
            if step.note is None or rng.random() >= amount:
                continue
            if rng.random() < 0.22:
                target = (row + rng.choice((-2, 2, 4))) % project.rows
                if project.pattern[channel][target].note is None:
                    project.pattern[channel][target] = Step(step.note, step.velocity, step.effect)
                    step.note = None
            else:
                pitch_class = min(scale, key=lambda item: abs(item - ((step.note - project.root) % 12)))
                index = scale.index(pitch_class)
                next_index = max(0, min(len(scale) - 1, index + rng.choice((-1, 1))))
                step.note += scale[next_index] - scale[index]
            changes += 1
    for row in range(project.rows):
        if row % 2 == 0 and rng.random() < amount * 0.22:
            project.pattern[0][row] = Step(rng.choice((36, 38, 42)), rng.randrange(7, 14), "HIT")
            changes += 1
        if project.track_count >= 6 and row % 4 and rng.random() < amount * .18:
            project.pattern[4][row] = Step(rng.choice((37, 42, 46)), rng.randrange(5, 9), "PCK")
            changes += 1
    return changes


def theme_variation(project: TrackerProject, theme: TrackerProject, generation: int, seed: int | None = None) -> int:
    """Build a bounded musical variation from an immutable primary theme.

    Unlike free mutation, every generation starts from ``theme`` instead of
    the previous variation. Strong drum beats, bar-root bass notes, chord
    downbeats and lead downbeats are protected. The eighth generation is a
    deliberate homecoming to the exact theme, creating an endless phrase arc
    without cumulative harmonic drift.
    """
    if project.rows != theme.rows or len(theme.pattern) != CHANNEL_COUNT:
        raise ValueError("variation theme must match the six-lane project")

    def clone_pattern(source: list[list[Step]]) -> list[list[Step]]:
        return [[Step(step.note, step.velocity, step.effect) for step in channel] for channel in source]

    project.pattern = clone_pattern(theme.pattern)
    phase = (max(1, int(generation)) - 1) % 8
    if phase == 7:
        return 0

    rng = random.Random(seed if seed is not None else theme.seed + max(1, int(generation))*104729)
    amount = (.10, .14, .18, .12, .20, .16, .13)[phase]
    scale = SCALE_MODES.get(theme.mode, SCALE_MODES["aeolian"])
    changes = 0

    def scale_move(note: int, distance: int) -> int:
        relative = note - theme.root
        octave, pitch_class = divmod(relative, 12)
        index = min(range(len(scale)), key=lambda item: abs(scale[item] - pitch_class))
        target = index + distance
        octave += target // len(scale)
        target %= len(scale)
        return theme.root + octave*12 + scale[target]

    # Rhythm: preserve the four structural quarter-note anchors. Hats, ghost
    # kicks and fills can breathe around them; the fourth variation becomes a
    # restrained breakdown before energy rises again.
    breakdown = phase == 3
    for row, step in enumerate(project.pattern[0]):
        pos = row % 16
        if pos in (0, 4, 8, 12):
            continue
        if step.note in (42, 46) and rng.random() < amount*(1.25 if breakdown else .72):
            if breakdown or rng.random() < .42:
                project.pattern[0][row] = Step()
            else:
                project.pattern[0][row] = Step(46 if step.note == 42 else 42, max(5, step.velocity-1), "FLL")
            changes += 1
        elif step.note == 36 and rng.random() < amount*.45:
            project.pattern[0][row] = Step()
            changes += 1
        elif step.note is None and pos in (2, 6, 10, 14) and rng.random() < amount*(.55 if breakdown else 1.05):
            note = 42 if rng.random() < .82 else 46
            project.pattern[0][row] = Step(note, 5+rng.randrange(4), "FLL")
            changes += 1
        elif step.note is None and pos in (7, 11, 15) and not breakdown and rng.random() < amount*.28:
            project.pattern[0][row] = Step(36, 7+rng.randrange(3), "GHO")
            changes += 1

    # Bass: bar roots are the harmonic identity. Only pickups and secondary
    # notes may disappear, move one scale degree, or answer the root.
    for row, step in enumerate(project.pattern[1]):
        if row % 16 == 0:
            continue
        if step.note is not None and rng.random() < amount*.72:
            if breakdown or rng.random() < .34:
                project.pattern[1][row] = Step()
            else:
                project.pattern[1][row] = Step(scale_move(step.note, rng.choice((-1, 1))),
                                               max(7, step.velocity-1), "VAR")
            changes += 1
        elif step.note is None and row % 16 in (10, 14) and not breakdown and rng.random() < amount*.34:
            anchor = project.pattern[1][row-row%16]
            if anchor.note is not None:
                project.pattern[1][row] = Step(scale_move(anchor.note, rng.choice((-1, 1))), 7+rng.randrange(3), "PUP")
                changes += 1

    # Chord downbeats never move. Mid-bar answers may drop out or reappear,
    # giving vapor and lo-fi pads arrangement motion without changing the song.
    for bar in range(project.rows//16):
        row = bar*16+8
        step = project.pattern[2][row]
        if step.note is not None and rng.random() < amount*(1.15 if breakdown else .55):
            project.pattern[2][row] = Step()
            changes += 1
        elif step.note is None and not breakdown and rng.random() < amount*.48:
            anchor = project.pattern[2][bar*16]
            if anchor.note is not None:
                project.pattern[2][row] = Step(scale_move(anchor.note, 2), 7+rng.randrange(3), "AIR")
                changes += 1

    # Lead: retain every bar's opening motif, then make phrase-level answers,
    # echoes and one-degree melodic substitutions elsewhere.
    for row, step in enumerate(list(project.pattern[3])):
        if row % 16 == 0 or step.note is None:
            continue
        if rng.random() < amount*(1.42 if breakdown else 1.08):
            if breakdown and rng.random() < .70:
                project.pattern[3][row] = Step()
            elif rng.random() < .24:
                target = (row+rng.choice((-2, 2))) % project.rows
                if target % 16 and project.pattern[3][target].note is None:
                    project.pattern[3][target] = Step(step.note, max(5, step.velocity-2), "ECO")
                    project.pattern[3][row] = Step()
                else:
                    project.pattern[3][row] = Step(scale_move(step.note, rng.choice((-1, 1))), step.velocity, "VAR")
            else:
                project.pattern[3][row] = Step(scale_move(step.note, rng.choice((-1, 1))), step.velocity, "VAR")
            changes += 1

    if theme.track_count >= 6:
        # Auxiliary layers can breathe more freely because the four-channel
        # spine remains protected underneath them.
        for row, step in enumerate(project.pattern[4]):
            if row % 4 == 0:
                continue
            if step.note is not None and rng.random() < amount * (1.35 if breakdown else .82):
                project.pattern[4][row] = Step()
                changes += 1
            elif step.note is None and row % 16 in (3, 7, 14) and not breakdown and rng.random() < amount * .62:
                project.pattern[4][row] = Step(rng.choice((37, 42, 46)), 5 + rng.randrange(3), "PCK")
                changes += 1
        for row, step in enumerate(project.pattern[5]):
            if step.note is not None and rng.random() < amount * (1.18 if breakdown else .48):
                if breakdown:
                    project.pattern[5][row] = Step()
                else:
                    project.pattern[5][row] = Step(scale_move(step.note, rng.choice((-1, 1))), step.velocity, "AIR")
                changes += 1

    # Guarantee audible iteration even for an unusually sparse theme/seed.
    if changes == 0:
        row = 2
        step = project.pattern[0][row]
        project.pattern[0][row] = Step(46 if step.note == 42 else 42, 7, "FLL")
        changes = 1
    return changes


@dataclass
class Voice:
    note: int = 60
    phase: float = 0.0
    phase2: float = 0.0
    age: int = 0
    velocity: float = 1.0
    active: bool = False
    sub_phase: float = 0.0
    filter_z: float = 0.0
    effect: str = "..."


@dataclass
class ScreenSpark:
    x: float
    y: float
    vx: float
    vy: float
    ttl: float
    glyph: str
    color: int


class SynthCore:
    """Sample-accurate six-voice synth shared by live playback and export."""

    def __init__(self, project: TrackerProject, sample_rate: int = 44100, solo: int | None = None):
        self.project = project
        self.sample_rate = sample_rate
        self.solo = solo
        self.voices = [Voice() for _ in range(CHANNEL_COUNT)]
        self.current_row = 0
        self.sample_in_row = 0
        self.playing = False
        self.master = 0.82
        self.lock = threading.RLock()
        self.reseed()
        self.scope = np.zeros(512, dtype=np.float32)
        self._scope_cursor = 0
        self.completed_cycles = 0

    def reseed(self) -> None:
        self.rngs = [np.random.default_rng(self.project.seed + channel * 1009) for channel in range(CHANNEL_COUNT)]

    def row_samples(self, row: int) -> int:
        base = self.sample_rate * 60.0 / self.project.bpm / 4.0
        swing = self.project.swing if row % 2 == 0 else -self.project.swing
        return max(32, int(round(base * (1.0 + swing))))

    def trigger(self, channel: int, step: Step) -> None:
        if step.note is None:
            return
        self.voices[channel] = Voice(
            note=step.note,
            phase=0.0,
            phase2=0.0,
            age=0,
            velocity=clamp(step.velocity / 15.0, 0.05, 1.0),
            active=True,
            effect=step.effect,
        )

    def trigger_row(self) -> None:
        for channel in range(CHANNEL_COUNT):
            if self.solo is None or self.solo == channel:
                self.trigger(channel, self.project.pattern[channel][self.current_row])

    def start(self, row: int = 0) -> None:
        with self.lock:
            self.current_row = row % self.project.rows
            self.sample_in_row = 0
            self.completed_cycles = 0
            self.voices = [Voice() for _ in range(CHANNEL_COUNT)]
            self.playing = True
            self.trigger_row()

    def stop(self) -> None:
        with self.lock:
            self.playing = False
            self.voices = [Voice() for _ in range(CHANNEL_COUNT)]

    def toggle(self) -> None:
        if self.playing:
            self.stop()
        else:
            completed_cycles = self.completed_cycles
            self.start(self.current_row)
            self.completed_cycles = completed_cycles

    def audition(self, channel: int, note: int) -> None:
        with self.lock:
            self.trigger(channel, Step(note, 13, "AUD"))

    def advance_row(self) -> None:
        self.current_row = (self.current_row + 1) % self.project.rows
        if self.current_row == 0:
            self.completed_cycles += 1
        self.trigger_row()

    @staticmethod
    def table_wave(waveform: str, phase: Any, phase2: Any, instrument: Instrument, color: float) -> Any:
        if waveform == "SINE":
            return np.sin(2 * np.pi * phase)
        if waveform == "SQUARE":
            return np.where(phase < 0.5, 1.0, -1.0)
        if waveform == "SAW":
            return 2.0 * phase - 1.0
        if waveform == "TRIANGLE":
            return 1.0 - 4.0 * np.abs(phase - 0.5)
        if waveform == "PULSE":
            return np.where(phase < instrument.pulse, 1.0, -1.0)
        if waveform == "ORGAN":
            return (
                np.sin(2 * np.pi * phase)
                + 0.52 * np.sin(4 * np.pi * phase)
                + 0.24 * np.sin(6 * np.pi * phase)
                + color * 0.14 * np.sin(8 * np.pi * phase)
            ) / 1.90
        if waveform == "FM":
            return np.sin(2 * np.pi * phase + (1.0 + color * 8.0) * np.sin(2 * np.pi * phase2))
        if waveform == "RING":
            return np.sin(2 * np.pi * phase) * np.sin(2 * np.pi * phase2)
        if waveform == "METAL":
            return np.tanh(1.8 * (np.sin(2 * np.pi * phase) + 0.7 * np.sin(2 * np.pi * phase * 2.414)))
        if waveform == "WOBBLE":
            square = np.where(phase < (0.18 + color * 0.62), 1.0, -1.0)
            return np.tanh((2.0 * phase - 1.0) * 2.2 + square * (0.25 + color * 0.45))
        if waveform == "REESE":
            a = 2.0 * phase - 1.0
            b = 2.0 * ((phase * (1.003 + color * 0.018) + 0.17) % 1.0) - 1.0
            return np.tanh((a + b) * (1.2 + color * 1.8)) * 0.72
        if waveform == "LIQUID":
            carrier = np.sin(2 * np.pi * phase + (2.0 + color * 10.0) * np.sin(2 * np.pi * phase2))
            return np.tanh(carrier * (1.4 + color * 2.4))
        if waveform == "GROWL":
            vowel = np.sin(2 * np.pi * phase) + 0.55 * np.sin(6 * np.pi * phase + color * 4.0)
            vowel += 0.34 * np.sin(10 * np.pi * phase2)
            return np.tanh(vowel * (1.2 + color * 2.8)) * 0.72
        if waveform == "BUBBLE":
            bend = phase + color * 0.19 * np.sin(2 * np.pi * phase2)
            return np.sin(2 * np.pi * bend * (1.0 + 2.0 * phase)) * (0.65 + 0.35 * np.sin(2 * np.pi * phase2))
        if waveform == "ROUND":
            return np.sin(2*np.pi*phase) + .18*np.sin(4*np.pi*phase) + .06*np.sin(6*np.pi*phase)
        if waveform == "VELVET":
            return .78*np.sin(2*np.pi*phase) + .16*np.sin(4*np.pi*phase) + .06*np.sin(8*np.pi*phase)
        if waveform == "RUBBER":
            bent = phase + (.035 + color*.055)*np.sin(2*np.pi*phase2)
            return np.tanh(1.35*np.sin(2*np.pi*bent))
        if waveform == "DUBSUB":
            return .88*np.sin(2*np.pi*phase) + .12*np.sin(4*np.pi*phase + color*np.pi)
        if waveform == "HOLLOW":
            return .72*np.sin(2*np.pi*phase) + .20*np.sin(6*np.pi*phase) - .08*np.sin(10*np.pi*phase)
        if waveform == "808 SUB":
            return .94*np.sin(2*np.pi*phase) + .06*np.sin(4*np.pi*phase)
        if waveform == "808 TAPE":
            body = .90*np.sin(2*np.pi*phase) + .16*np.sin(4*np.pi*phase + .18)
            return np.tanh(body*(1.18+color*.72))*.90
        if waveform == "BOOM BAP":
            return .76*np.sin(2*np.pi*phase) + .17*np.sin(4*np.pi*phase) + .07*np.sin(6*np.pi*phase)
        if waveform == "DUSTY KEYS":
            return .72*np.sin(2*np.pi*phase) + .17*np.sin(4*np.pi*phase+.14) + .08*np.sin(6*np.pi*phase2)
        if waveform == "LOWRIDER":
            body = .86*np.sin(2*np.pi*phase) + .11*np.sin(4*np.pi*phase+color*.4)
            return body + .03*np.tanh(3.0*(2.0*phase-1.0))
        if waveform == "VHS PAD":
            flutter = phase + (.003 + color*.006)*np.sin(2*np.pi*phase2)
            body = .72*np.sin(2*np.pi*flutter) + .19*np.sin(4*np.pi*phase+.16)
            return body + .09*np.sin(6*np.pi*phase2)
        if waveform == "CASSETTE KEYS":
            triangle = 1.0 - 4.0*np.abs(phase-.5)
            body = .64*np.sin(2*np.pi*phase) + .25*triangle
            return body + .11*np.sin(6*np.pi*phase2+.12)
        if waveform == "TAPE FLUTE":
            flutter = phase + (.002 + color*.004)*np.sin(2*np.pi*phase2)
            return .86*np.sin(2*np.pi*flutter) + .10*np.sin(4*np.pi*phase) + .04*np.sin(8*np.pi*phase2)
        if waveform == "MALL BASS":
            body = .91*np.sin(2*np.pi*phase) + .07*np.sin(4*np.pi*phase+.22)
            return body + .02*np.tanh(2.4*(2.0*phase-1.0))
        return np.zeros_like(phase)

    def lowpass(self, mono: Any, voice: Voice, cutoff: float) -> Any:
        """Stable one-pole tone shaper with state preserved across callbacks."""
        cutoff = clamp(cutoff, 120.0, self.sample_rate * .44)
        alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / self.sample_rate)
        output = np.empty_like(mono, dtype=np.float32)
        z = voice.filter_z
        for index, sample in enumerate(mono):
            z += alpha * (float(sample) - z)
            output[index] = z
        voice.filter_z = z
        return output

    def _render_drum(self, channel: int, voice: Voice, count: int, instrument: Instrument) -> Any:
        age = (voice.age + np.arange(count)) / self.sample_rate
        if voice.note <= 36:
            boom = clamp(instrument.boom, 0.0, 1.0)
            fundamental = 43.0 * (2.0 ** ((voice.note - 36) / 12.0))
            pitch = fundamental + (112.0 + 38.0*boom) * np.exp(-age * (24.0-8.0*boom))
            phase = voice.phase + np.cumsum(pitch / self.sample_rate)
            tail_seconds = .11 + boom*1.42 + instrument.decay*.18
            envelope = np.exp(-age / tail_seconds)
            body = np.sin(2*np.pi*phase) + (.07+.08*instrument.warmth)*np.sin(4*np.pi*phase)
            click = self.rngs[channel].normal(0.0, 1.0, count) * np.exp(-age*105.0) * (.035+.045*instrument.dust)
            mono = body*envelope + click
            voice.phase = float(phase[-1] % 1.0)
        elif voice.note == 37:
            noise = self.rngs[channel].normal(0.0, 1.0, count)
            tone = np.sin(2*np.pi*(418.0*age+voice.phase))
            mono = (.80*tone+.20*noise)*np.exp(-age*38.0)*.62
            voice.phase = float((voice.phase + 418.0*count/self.sample_rate) % 1.0)
        elif voice.note == 38:
            noise = self.rngs[channel].normal(0.0, 1.0, count)
            tone = np.sin(2 * np.pi * (176.0 * age + voice.phase))
            shell = np.sin(2 * np.pi * (108.0 * age + voice.phase*.7))
            mono = (0.62*noise + 0.25*tone + 0.13*shell) * np.exp(-age*(16.0-3.0*instrument.dust))
            voice.phase = float((voice.phase + 183.0 * count / self.sample_rate) % 1.0)
        elif voice.note == 39:
            noise = self.rngs[channel].normal(0.0, 1.0, count)
            clap = np.exp(-age*23.0)
            for delay in (.012, .025):
                clap += np.where(age >= delay, np.exp(-(age-delay)*34.0), 0.0)*.58
            mono = noise*clap*.48
        elif voice.note == 56:
            low = np.sign(np.sin(2*np.pi*(536.0*age+voice.phase)))
            high = np.sign(np.sin(2*np.pi*(804.0*age+voice.phase*.7)))
            mono = (.56*low+.44*high)*np.exp(-age*8.2)*.38
            voice.phase = float((voice.phase + 536.0*count/self.sample_rate) % 1.0)
        else:
            noise = self.rngs[channel].normal(0.0, 1.0, count)
            decay = 8.5 if voice.note == 46 else 42.0
            level = .42 if voice.note == 46 else .55
            mono = np.concatenate(([noise[0]], np.diff(noise))) * np.exp(-age*decay)*level
        return mono.astype(np.float32)

    def _render_voice(self, channel: int, count: int) -> Any:
        voice = self.voices[channel]
        if not voice.active:
            return np.zeros(count, dtype=np.float32)
        instrument = self.project.instruments[channel]
        if channel in DRUM_CHANNELS:
            mono = self._render_drum(channel, voice, count, instrument)
            envelope = np.ones(count, dtype=np.float32)
        else:
            frequency = note_frequency(voice.note) * (2.0 ** (instrument.detune / 12.0))
            indices = np.arange(count, dtype=np.float64)
            phase = (voice.phase + indices * frequency / self.sample_rate) % 1.0
            phase2 = (voice.phase2 + indices * frequency * (1.5 + instrument.color * 2.5) / self.sample_rate) % 1.0
            if channel == 2:
                waves = []
                for interval in chord_intervals(voice.effect):
                    ratio = 2.0 ** (interval / 12)
                    chord_phase = (voice.phase + indices * frequency * ratio / self.sample_rate) % 1.0
                    waves.append(self.table_wave(instrument.waveform, chord_phase, phase2, instrument, instrument.color))
                mono = sum(waves) / max(1, len(waves))
            elif instrument.waveform == "NOISE":
                mono = self.rngs[channel].normal(0.0, 0.55, count)
            else:
                mono = self.table_wave(instrument.waveform, phase, phase2, instrument, instrument.color)
            age = (voice.age + indices) / self.sample_rate
            # Tempo-locked amplitude/formant motion.  This is deliberately part
            # of the synth path, so live playback, stems and master export match.
            if instrument.wobble > 0.001:
                beat_hz = self.project.bpm / 60.0
                division = (0.5, 1.0, 2.0, 3.0, 4.0)[min(4, int(instrument.color * 5.0))]
                lfo = 0.5 + 0.5 * np.sin(2 * np.pi * age * beat_hz * division + voice.phase2 * 6.0)
                gate = (1.0 - instrument.wobble * 0.72) + instrument.wobble * 0.72 * np.power(lfo, 1.5)
                mono = mono * gate
            if instrument.sub > 0.001:
                sub_phase = (voice.sub_phase + indices * frequency * .5 / self.sample_rate) % 1.0
                mono = mono + instrument.sub * np.sin(2*np.pi*sub_phase)
                voice.sub_phase = float((voice.sub_phase + count * frequency * .5 / self.sample_rate) % 1.0)
            if instrument.drive > 0.001:
                gain = 1.0 + instrument.drive * 7.0
                mono = np.tanh(mono * gain) / np.tanh(gain)
            attack = max(0.0005, instrument.attack)
            envelope = np.minimum(1.0, age / attack) * np.exp(-age / max(0.03, instrument.decay))
            voice.phase = float((voice.phase + count * frequency / self.sample_rate) % 1.0)
            voice.phase2 = float((voice.phase2 + count * frequency * (1.5 + instrument.color * 2.5) / self.sample_rate) % 1.0)
        # Dust enters before the dark tone stage: it roughens pristine digital
        # edges like a worn sampler/tape path without adding exposed shrill fizz.
        if instrument.dust > .001:
            texture = self.rngs[channel].normal(0.0, .014*instrument.dust, count)
            mono = mono + texture
        # The stateful tone pass moves raw digital edges behind the fundamental.
        # Warmth provides soft transformer-like saturation without harsh clipping.
        mono = self.lowpass(mono, voice, instrument.cutoff)
        if instrument.warmth > .001:
            gain = 1.0 + instrument.warmth * 2.2
            mono = np.tanh(mono * gain) / np.tanh(gain)
        voice.age += count
        if voice.age / self.sample_rate > max(0.35, instrument.decay * 7.0):
            voice.active = False
        return (mono * envelope * instrument.volume * voice.velocity).astype(np.float32)

    def _render_chunk(self, count: int) -> Any:
        stereo = np.zeros((count, 2), dtype=np.float32)
        for channel in range(CHANNEL_COUNT):
            if self.solo is not None and channel != self.solo:
                continue
            mono = self._render_voice(channel, count)
            pan = clamp(self.project.instruments[channel].pan, -1.0, 1.0)
            left = math.cos((pan + 1.0) * math.pi / 4.0)
            right = math.sin((pan + 1.0) * math.pi / 4.0)
            stereo[:, 0] += mono * left
            stereo[:, 1] += mono * right
        return np.tanh(stereo * self.master).astype(np.float32)

    def render(self, frames: int) -> Any:
        with self.lock:
            output = np.zeros((frames, 2), dtype=np.float32)
            if not self.playing:
                # The audio callback still advances audition voices while the
                # tracker transport is stopped, so waveform design is immediate.
                output[:] = self._render_chunk(frames)
                mono = output.mean(axis=1)
                if len(mono) >= len(self.scope):
                    self.scope[:] = mono[-len(self.scope) :]
                else:
                    shift = len(mono)
                    self.scope[:-shift] = self.scope[shift:]
                    self.scope[-shift:] = mono
                return output
            cursor = 0
            while cursor < frames:
                row_length = self.row_samples(self.current_row)
                # A live tempo increase can make the new row shorter than the
                # samples already consumed under the old tempo. Advance cleanly
                # rather than passing a negative frame count into NumPy.
                if self.sample_in_row >= row_length:
                    self.sample_in_row = 0
                    self.advance_row()
                    continue
                count = min(frames - cursor, row_length - self.sample_in_row)
                output[cursor : cursor + count] = self._render_chunk(count)
                cursor += count
                self.sample_in_row += count
                if self.sample_in_row >= row_length:
                    self.sample_in_row = 0
                    self.advance_row()
            mono = output.mean(axis=1)
            if len(mono) >= len(self.scope):
                self.scope[:] = mono[-len(self.scope) :]
            else:
                shift = len(mono)
                self.scope[:-shift] = self.scope[shift:]
                self.scope[-shift:] = mono
            return output

    def preview_waveform(self, channel: int, samples: int = 256) -> Any:
        instrument = self.project.instruments[channel]
        phase = np.linspace(0.0, 1.0, samples, endpoint=False)
        phase2 = (phase * (1.5 + instrument.color * 2.5)) % 1.0
        if channel in DRUM_CHANNELS or instrument.waveform == "NOISE":
            rng = np.random.default_rng(self.project.seed + channel)
            return rng.uniform(-1.0, 1.0, samples)
        return self.table_wave(instrument.waveform, phase, phase2, instrument, instrument.color)

    def activity_levels(self) -> tuple[float, ...]:
        """Return cheap envelope estimates for the onscreen hardware meters."""
        with self.lock:
            levels = []
            for channel, voice in enumerate(self.voices):
                if not voice.active:
                    levels.append(0.0)
                    continue
                instrument = self.project.instruments[channel]
                age = voice.age / self.sample_rate
                speed = 18.0 if channel in DRUM_CHANNELS else 1.0 / max(0.03, instrument.decay)
                levels.append(clamp(voice.velocity * math.exp(-age * speed), 0.0, 1.0))
            return tuple(levels)  # type: ignore[return-value]


class RawPCMOutput:
    """A thin signed-int16 output bridge; ALSA is used through PortAudio on Linux."""

    def __init__(self, core: SynthCore, device: str | int | None = None, latency: str = "low", no_audio: bool = False):
        self.core = core
        self.device = device
        self.latency = latency
        self.no_audio = no_audio
        self.stream: Any = None
        self.description = "NO AUDIO"
        self.xruns = 0

    def _callback(self, outdata: Any, frames: int, _time_info: Any, status: Any) -> None:
        if status:
            self.xruns += 1
        audio = self.core.render(frames)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
        outdata[:] = pcm.tobytes()

    def start(self) -> None:
        if self.no_audio:
            return
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is missing; install requirements.txt or use --no-audio") from exc
        selected: Any = self.device
        if isinstance(selected, str) and selected.isdigit():
            selected = int(selected)
        info = sd.query_devices(selected, "output")
        hostapis = sd.query_hostapis()
        host = hostapis[info["hostapi"]]["name"]
        self.description = f"{host} :: {info['name']}"
        self.stream = sd.RawOutputStream(
            samplerate=self.core.sample_rate,
            blocksize=256,
            channels=2,
            dtype="int16",
            latency=self.latency,
            device=selected,
            callback=self._callback,
        )
        self.stream.start()

    def close(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None


def write_wav(path: Path, audio: Any, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm.tobytes())


def render_project(project: TrackerProject, sample_rate: int, solo: int | None = None) -> Any:
    core = SynthCore(project.clone(), sample_rate, solo=solo)
    total = sum(core.row_samples(row) for row in range(project.rows))
    core.start(0)
    chunks = []
    remaining = total
    while remaining:
        count = min(4096, remaining)
        chunks.append(core.render(count))
        remaining -= count
    return np.concatenate(chunks, axis=0)


def midi_track(events: list[tuple[int, bytes]]) -> bytes:
    body = bytearray()
    previous = 0
    for tick, payload in sorted(events, key=lambda item: (item[0], item[1][0] & 0xF0)):
        body.extend(variable_length(max(0, tick - previous)))
        body.extend(payload)
        previous = tick
    body.extend(b"\x00\xff\x2f\x00")
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def write_midi(path: Path, project: TrackerProject) -> None:
    division = 96
    row_ticks = division // 4
    tempo = int(60_000_000 / project.bpm)
    tempo_track = midi_track([(0, b"\xff\x51\x03" + tempo.to_bytes(3, "big"))])
    tracks = [tempo_track]
    melodic_midi_channels = {1: 0, 2: 1, 3: 2, 5: 3}
    for channel in range(CHANNEL_COUNT):
        midi_channel = 9 if channel in DRUM_CHANNELS else melodic_midi_channels[channel]
        events: list[tuple[int, bytes]] = []
        for row, step in enumerate(project.pattern[channel]):
            if step.note is None:
                continue
            notes = (step.note,)
            if channel == 2:
                notes = tuple(step.note + interval for interval in chord_intervals(step.effect))
            start = row * row_ticks
            length = row_ticks * (4 if channel == 2 else 1)
            for note in notes:
                velocity = max(1, min(127, step.velocity * 8))
                events.append((start, bytes((0x90 | midi_channel, note, velocity))))
                events.append((start + length, bytes((0x80 | midi_channel, note, 0))))
        tracks.append(midi_track(events))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), division)
    path.write_bytes(header + b"".join(tracks))


def export_project(project: TrackerProject, root: Path, sample_rate: int = 44100) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = root / f"{stamp}-{project.style.lower().replace(' ', '-')}"
    suffix = 2
    while folder.exists():
        folder = root / f"{stamp}-{project.style.lower().replace(' ', '-')}-{suffix}"
        suffix += 1
    folder.mkdir(parents=True)
    master = render_project(project, sample_rate)
    write_wav(folder / "master.wav", master, sample_rate)
    for channel, name in enumerate(CHANNEL_NAMES):
        stem = render_project(project, sample_rate, solo=channel)
        write_wav(folder / f"stem_{channel + 1}_{name.lower()}.wav", stem, sample_rate)
    write_midi(folder / "pattern.mid", project)
    project.save(folder / "project.json")
    return folder


def waveform_line(values: Any, width: int) -> str:
    if width <= 0:
        return ""
    indices = np.linspace(0, len(values) - 1, width).astype(int)
    return "".join(BLOCKS[int(clamp((float(values[index]) + 1.0) * 4.0, 0, 8))] for index in indices)


class TrackerUI:
    def __init__(self, project: TrackerProject, core: SynthCore, output: RawPCMOutput, project_path: Path, export_root: Path):
        self.project = project
        self.core = core
        self.output = output
        self.project_path = project_path
        self.export_root = export_root
        self.cursor_channel = 0
        self.cursor_row = 0
        self.page = 0
        self.style_index = next((i for i, style in enumerate(STYLES) if style["name"] == project.style), 0)
        self.insert_mode = False
        self.wave_lab = False
        self.help = False
        self.octave = 3
        self.running = True
        self.message = "PRESS G: MAKE SONG   SPACE: PLAY   H: HELP"
        self.message_until = 0.0
        self.frame = 0
        self.last_fx_time = time.monotonic()
        self.last_fx_row = -1
        self.sparks: list[ScreenSpark] = []
        self.previous_scope = np.zeros(512, dtype=np.float32)

    @staticmethod
    def safe_add(screen: Any, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = screen.getmaxyx()
        if not (0 <= y < height and 0 <= x < width):
            return
        try:
            screen.addnstr(y, x, text, max(0, width - x - 1), attr)
        except curses.error:
            pass

    @staticmethod
    def color(pair: int) -> int:
        return curses.color_pair(pair) if curses.has_colors() else 0

    @staticmethod
    def popup_color(pair: int) -> int:
        """Popup palette: the same foreground colors pinned to opaque black."""
        return curses.color_pair(pair + 7) if curses.has_colors() else 0

    def box(
        self,
        screen: Any,
        y: int,
        x: int,
        height: int,
        width: int,
        title: str,
        attr: int = 0,
        fill_attr: int | None = None,
    ) -> None:
        if width < 4 or height < 2:
            return
        if fill_attr is not None:
            # Redraw every cell, not merely the border. This prevents the live
            # tracker from bleeding through transparent terminal backgrounds.
            for row in range(y, y + height):
                self.safe_add(screen, row, x, " " * width, fill_attr)
        self.safe_add(screen, y, x, "+" + "-" * (width - 2) + "+", attr)
        for row in range(y + 1, y + height - 1):
            self.safe_add(screen, row, x, "|", attr)
            self.safe_add(screen, row, x + width - 1, "|", attr)
        self.safe_add(screen, y + height - 1, x, "+" + "-" * (width - 2) + "+", attr)
        self.safe_add(screen, y, x + 2, f" {title[:width - 6]} ", attr | curses.A_BOLD)

    def flash(self, text: str, seconds: float = 2.5) -> None:
        self.message = text
        self.message_until = time.monotonic() + seconds

    def mode_name(self) -> str:
        if self.help:
            return "HELP"
        if self.wave_lab:
            return "WAVE FORGE"
        if self.insert_mode:
            return f"INSERT O{self.octave}"
        return "NAVIGATE"

    def mode_color(self) -> int:
        if self.help:
            return 4
        if self.wave_lab:
            return 2
        if self.insert_mode:
            return 5
        return 3

    def burst(self, color: int, count: int = 10, origin: float = 0.50) -> None:
        for _ in range(count):
            self.sparks.append(
                ScreenSpark(
                    x=origin + random.uniform(-0.04, 0.04),
                    y=random.uniform(0.35, 0.70),
                    vx=random.uniform(-0.42, 0.42),
                    vy=random.uniform(-0.55, 0.08),
                    ttl=random.uniform(0.35, 1.20),
                    glyph=random.choice((".", "+", "*", "x", "o")),
                    color=color,
                )
            )

    def tick_fx(self) -> None:
        now = time.monotonic()
        delta = min(0.08, now - self.last_fx_time)
        self.last_fx_time = now
        alive = []
        for spark in self.sparks:
            spark.ttl -= delta
            if spark.ttl <= 0:
                continue
            spark.x += spark.vx * delta
            spark.y += spark.vy * delta
            spark.vy += 0.70 * delta
            alive.append(spark)
        self.sparks = alive[-180:]
        if self.core.playing and self.core.current_row != self.last_fx_row:
            self.last_fx_row = self.core.current_row
            colors = (3, 6, 2, 1, 4, 5)
            for channel in range(CHANNEL_COUNT):
                if self.project.pattern[channel][self.core.current_row].note is not None:
                    self.burst(colors[channel], 3 + channel, 0.10 + channel * 0.16)

    def draw_performance_rack(self, screen: Any, y: int, width: int) -> None:
        levels = self.core.activity_levels()
        colors = (3, 6, 2, 1, 4, 5)
        cursor_x = 2
        for channel, level in enumerate(levels):
            lit = int(round(level * 6))
            meter = "#" * lit + "." * (6 - lit)
            label = f"{channel + 1}:{CHANNEL_NAMES[channel]:<5}[{meter}]"
            attr = self.color(colors[channel]) | (curses.A_BOLD if level > 0.08 else curses.A_DIM)
            self.safe_add(screen, y, cursor_x, label, attr)
            cursor_x += len(label) + 2
        beat = (self.core.current_row % 16) // 4 if self.core.playing else -1
        lamps = " ".join("@" if index == beat else "o" for index in range(4))
        lamp_text = f"BEAT [{lamps}]"
        raster_width = max(0, width - cursor_x - len(lamp_text) - 5)
        raster_chars = "=-~."
        raster = "".join(raster_chars[(index + self.frame // 2) % len(raster_chars)] for index in range(raster_width))
        self.safe_add(screen, y, cursor_x, raster, self.color(2) | curses.A_DIM)
        self.safe_add(screen, y, max(cursor_x, width - len(lamp_text) - 2), lamp_text, self.color(4) | curses.A_BOLD)

    def draw_scope(self, screen: Any, y: int, x: int, height: int, width: int) -> None:
        phase = ("PHOSPHOR", "VECTOR", "RASTER", "PCM BUS")[self.frame // 24 % 4]
        self.box(screen, y, x, height, width, f"RAW PCM OSCILLOSCOPE // {phase}", self.color(1))
        values = self.core.scope.copy() if self.core.playing else self.core.preview_waveform(self.cursor_channel, 512)
        inner_h = max(1, height - 2)
        indices = np.linspace(0, len(values) - 1, max(1, width - 4)).astype(int)
        ghost_indices = np.linspace(0, len(self.previous_scope) - 1, max(1, width - 4)).astype(int)
        center = y + 1 + inner_h // 2
        self.safe_add(screen, center, x + 2, "." * max(1, width - 4), self.color(7) | curses.A_DIM)
        scan_x = x + 2 + (self.frame % max(1, width - 4))
        for scan_y in range(y + 1, y + height - 1):
            self.safe_add(screen, scan_y, scan_x, ":", self.color(2) | curses.A_DIM)
        for column, index in enumerate(ghost_indices):
            ghost_row = center - int(float(self.previous_scope[index]) * max(1, (inner_h - 1) / 2))
            ghost_row = max(y + 1, min(y + height - 2, ghost_row))
            self.safe_add(screen, ghost_row, x + 2 + column, ".", self.color(6) | curses.A_DIM)
        for column, index in enumerate(indices):
            row = center - int(float(values[index]) * max(1, (inner_h - 1) / 2))
            row = max(y + 1, min(y + height - 2, row))
            glyph = "#" if (column + self.frame) % 5 else "*"
            self.safe_add(screen, row, x + 2 + column, glyph, self.color(3) | curses.A_BOLD)
        for spark in self.sparks:
            px = x + 2 + int(clamp(spark.x, 0.0, 1.0) * max(1, width - 5))
            py = y + 1 + int(clamp(spark.y, 0.0, 1.0) * max(1, height - 3))
            self.safe_add(screen, py, px, spark.glyph, self.color(spark.color) | curses.A_BOLD)
        self.previous_scope = values.copy()

    def draw_instrument(self, screen: Any, y: int, x: int, height: int, width: int) -> None:
        instrument = self.project.instruments[self.cursor_channel]
        self.box(screen, y, x, height, width, f"CH{self.cursor_channel + 1} {CHANNEL_NAMES[self.cursor_channel]}", self.color(2))
        lines = (
            f"{instrument.name}",
            f"WAVE  {instrument.waveform:<8}",
            f"VOL   {instrument.volume:0.2f}   PAN {instrument.pan:+0.2f}",
            f"ATK   {instrument.attack:0.3f}  DEC {instrument.decay:0.2f}",
            f"COLOR {instrument.color:0.2f}   PW  {instrument.pulse:0.2f}",
            waveform_line(self.core.preview_waveform(self.cursor_channel), max(8, width - 4)),
            "W:FORGE  I:NOTES  ENTER:AUDITION",
        )
        for index, line in enumerate(lines[: height - 2]):
            self.safe_add(screen, y + 1 + index, x + 2, line[: width - 4], self.color(7) | (curses.A_BOLD if index == 0 else 0))

    def draw_tracker(self, screen: Any, y: int, x: int, height: int, width: int) -> None:
        title = f"PATTERN 00  //  PAGE {self.page + 1}/4  //  MODE {self.mode_name()}"
        self.box(screen, y, x, height, width, title, self.color(4))
        channel_width = max(12, (width - 9) // CHANNEL_COUNT)
        header = "ROW " + "".join(f"| {name:<{channel_width - 2}}" for name in CHANNEL_NAMES)
        self.safe_add(screen, y + 1, x + 2, header[: width - 4], self.color(4) | curses.A_BOLD)
        visible = min(16, height - 3)
        start = self.page * 16
        for display_row in range(visible):
            row = start + display_row
            playing = self.core.playing and row == self.core.current_row
            row_attr = self.color(3) | curses.A_BOLD if playing else self.color(7)
            self.safe_add(screen, y + 2 + display_row, x + 2, f"{row:02X}  ", row_attr)
            for channel in range(CHANNEL_COUNT):
                step = self.project.pattern[channel][row]
                cell = f"{midi_name(step.note)} {step.velocity:X} {step.effect:<3}"
                cx = x + 6 + channel * channel_width
                selected = channel == self.cursor_channel and row == self.cursor_row
                attr = self.color(6) | curses.A_REVERSE | curses.A_BOLD if selected else row_attr
                self.safe_add(screen, y + 2 + display_row, cx, ("| " + cell).ljust(channel_width), attr)

    def draw_footer(self, screen: Any, height: int, width: int) -> None:
        play = "PLAY" if self.core.playing else "STOP"
        mode = self.mode_name()
        top = (
            f"MODE {mode:<10} // {play}  ROW {self.core.current_row:02X}  {self.project.bpm} BPM  SWING {self.project.swing:0.2f}  "
            f"STYLE {self.project.style}  AUDIO {self.output.description}  XRUN {self.output.xruns}"
        )
        self.safe_add(screen, height - 3, 2, top[: width - 4], self.color(self.mode_color()) | curses.A_BOLD)
        if self.insert_mode:
            keys = f"INSERT PIANO O{self.octave}: Z S X D C V G B H N J M ,  //  2-6 OCTAVE  DEL ERASE  I/ESC EXIT"
        elif self.wave_lab:
            keys = "WAVE FORGE: LEFT/RIGHT SHAPE  UP/DOWN COLOR  [ ] PULSE  A/Z ATTACK  D/C DECAY  R RANDOM  W/ENTER EXIT"
        elif self.help:
            keys = "HELP MODE: H / Q / ESC RETURNS TO TRACKER"
        else:
            keys = "G MAKE SONG  Y STYLE  M MUTATE  SPACE PLAY  I NOTES  W WAVE FORGE  E EXPORT  S SAVE  H HELP  Q QUIT"
        self.safe_add(screen, height - 2, 2, keys[: width - 4], self.color(self.mode_color()) | curses.A_BOLD)
        message = self.message if self.message_until == 0 or time.monotonic() < self.message_until else ""
        self.safe_add(screen, height - 1, 2, message[: width - 4], self.color(1) | curses.A_BOLD)

    def draw_wave_lab(self, screen: Any) -> None:
        height, width = screen.getmaxyx()
        panel_w, panel_h = min(90, width - 8), min(24, height - 5)
        x, y = (width - panel_w) // 2, (height - panel_h) // 2
        instrument = self.project.instruments[self.cursor_channel]
        black = self.popup_color(7)
        self.box(
            screen,
            y,
            x,
            panel_h,
            panel_w,
            "MODE: WAVEFORM FORGE // DIRECT OSCILLATOR DESIGN",
            self.popup_color(2) | curses.A_BOLD,
            fill_attr=black,
        )
        values = self.core.preview_waveform(self.cursor_channel, max(64, panel_w - 8))
        plot_y, plot_h = y + 3, max(5, panel_h - 12)
        center = plot_y + plot_h // 2
        self.safe_add(screen, center, x + 4, "-" * (panel_w - 8), self.popup_color(7) | curses.A_DIM)
        indices = np.linspace(0, len(values) - 1, panel_w - 8).astype(int)
        for column, index in enumerate(indices):
            py = center - int(float(values[index]) * max(1, plot_h // 2 - 1))
            ghost_y = min(plot_y + plot_h - 1, py + 1)
            self.safe_add(screen, ghost_y, x + 4 + column, ".", self.popup_color(6) | curses.A_DIM)
            self.safe_add(screen, py, x + 4 + column, "#", self.popup_color(3) | curses.A_BOLD)
        details = (
            f"CHANNEL {self.cursor_channel + 1} {CHANNEL_NAMES[self.cursor_channel]}   WAVE {instrument.waveform}",
            f"COLOR {instrument.color:0.2f}   PULSE WIDTH {instrument.pulse:0.2f}   ATTACK {instrument.attack:0.3f}s   DECAY {instrument.decay:0.2f}s",
            "LEFT/RIGHT waveform   UP/DOWN color   [/ ] pulse width   A/Z attack   D/C decay",
            "R forge random waveform   SPACE audition   ENTER/W/ESC return to tracker",
        )
        for index, line in enumerate(details):
            pair = 4 if index >= 2 else 7
            self.safe_add(screen, y + panel_h - 6 + index, x + 4, line[: panel_w - 8], self.popup_color(pair) | (curses.A_BOLD if index == 0 else 0))

    def draw_help(self, screen: Any) -> None:
        height, width = screen.getmaxyx()
        panel_w, panel_h = min(92, width - 8), min(26, height - 5)
        x, y = (width - panel_w) // 2, (height - panel_h) // 2
        black = self.popup_color(7)
        self.box(
            screen,
            y,
            x,
            panel_h,
            panel_w,
            "MODE: HELP // COMMAND DISK // ZERO THEORY REQUIRED",
            self.popup_color(4) | curses.A_BOLD,
            fill_attr=black,
        )
        lines = (
            f"YOU ARE IN HELP MODE. Selected: CH{self.cursor_channel + 1} {CHANNEL_NAMES[self.cursor_channel]} / row {self.cursor_row:02X}.",
            "FAST PATH: G makes a complete song. SPACE plays it. M makes a related mutation.",
            "E exports master.wav, six isolated WAV stems, MIDI, and an editable project.",
            "",
            "G          Generate a coherent four-bar song in the current style",
            "Y          Change style and immediately generate another song",
            "SPACE      Start/stop the hardware-timed tracker transport",
            "ARROWS     Move through tracker rows and channels; [ ] changes page",
            "TAB        Select the next channel/instrument",
            "I          Note-insert mode: Z S X D C V G B H N J M , is a piano",
            "2–6        Set note-entry octave; DELETE/BACKSPACE clears a step",
            "ENTER      Audition the selected note/instrument",
            "W          Open waveform forge for the selected channel",
            "+ / -      Tempo; < / > swing; C clears selected channel",
            "S          Save the editable tracker project",
            "E          Production export: master + stems + MIDI + project JSON",
            "H / Q      Close help / quit",
            "",
            "This is synthesis, not sample playback: the displayed waveform becomes raw PCM",
            "in real time. On Linux, PortAudio normally talks directly to ALSA/PipeWire.",
        )
        for index, line in enumerate(lines[: panel_h - 3]):
            pair = 3 if index < 2 else 4 if line and len(line) > 1 and line[1:11].strip() else 7
            self.safe_add(screen, y + 2 + index, x + 3, line[: panel_w - 6], self.popup_color(pair) | (curses.A_BOLD if index < 2 else 0))

    def draw(self, screen: Any) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 30 or width < 100:
            self.safe_add(screen, 2, 3, f"{APP} needs at least 100x30. Current: {width}x{height}.", curses.A_BOLD)
            self.safe_add(screen, 4, 3, "Resize the terminal or press Q.")
            screen.refresh()
            return
        self.frame += 1
        self.tick_fx()
        signal = ("*", "+", "x", "+")[self.frame // 3 % 4]
        title = f"{signal} {APP} // SIX LANE RAW PCM TRACKER // v{VERSION}"
        self.safe_add(screen, 0, 2, title, self.color(1) | curses.A_BOLD)
        badge = f"[ MODE: {self.mode_name()} ]"
        self.safe_add(screen, 0, max(2, width - len(badge) - 2), badge, self.color(self.mode_color()) | curses.A_REVERSE | curses.A_BOLD)
        self.safe_add(screen, 1, 2, f"{self.project.title}  ::  NO SAMPLES / NO PLUGINS / NO MODEL DOWNLOAD", self.color(7) | curses.A_DIM)
        self.draw_performance_rack(screen, 2, width)
        top_h = 10
        scope_w = max(58, int(width * 0.64))
        self.draw_scope(screen, 3, 1, top_h, scope_w)
        self.draw_instrument(screen, 3, scope_w + 1, top_h, width - scope_w - 2)
        tracker_y = 13
        tracker_h = max(10, height - tracker_y - 3)
        self.draw_tracker(screen, tracker_y, 1, tracker_h, width - 2)
        self.draw_footer(screen, height, width)
        if self.wave_lab:
            self.draw_wave_lab(screen)
        if self.help:
            self.draw_help(screen)
        screen.refresh()

    def selected_note(self) -> int:
        step = self.project.pattern[self.cursor_channel][self.cursor_row]
        return step.note if step.note is not None else 12 * (self.octave + 1)

    def save(self) -> None:
        self.project.save(self.project_path)
        self.flash(f"SAVED PROJECT -> {self.project_path}", 4.0)

    def export(self) -> None:
        was_playing = self.core.playing
        self.core.stop()
        self.flash("RENDERING MASTER + 6 STEMS + MIDI...", 30.0)
        folder = export_project(self.project, self.export_root, self.core.sample_rate)
        if was_playing:
            self.core.start(0)
        self.flash(f"EXPORT READY -> {folder}", 8.0)

    def forge_wave(self) -> None:
        instrument = self.project.instruments[self.cursor_channel]
        instrument.waveform = random.choice(WAVEFORMS if self.cursor_channel not in DRUM_CHANNELS else ("NOISE", "METAL", "SINE"))
        instrument.color = random.uniform(0.05, 0.98)
        instrument.pulse = random.uniform(0.12, 0.88)
        instrument.attack = random.uniform(0.001, 0.06)
        instrument.decay = random.uniform(0.12, 1.8 if self.cursor_channel == 2 else 0.75)
        instrument.detune = random.uniform(-0.18, 0.18)
        self.core.audition(self.cursor_channel, self.selected_note())
        self.burst((3, 6, 2, 1, 4, 5)[self.cursor_channel], 24, 0.10 + self.cursor_channel * 0.16)
        self.flash(f"FORGED {instrument.waveform} WAVEFORM")

    def handle_wave_lab(self, key: int) -> None:
        instrument = self.project.instruments[self.cursor_channel]
        if key in (ord("w"), ord("W"), 10, 13, 27):
            self.wave_lab = False
        elif key == curses.KEY_LEFT:
            instrument.waveform = WAVEFORMS[(WAVEFORMS.index(instrument.waveform) - 1) % len(WAVEFORMS)]
            self.core.audition(self.cursor_channel, self.selected_note())
        elif key == curses.KEY_RIGHT:
            instrument.waveform = WAVEFORMS[(WAVEFORMS.index(instrument.waveform) + 1) % len(WAVEFORMS)]
            self.core.audition(self.cursor_channel, self.selected_note())
        elif key == curses.KEY_UP:
            instrument.color = clamp(instrument.color + 0.04, 0.0, 1.0)
        elif key == curses.KEY_DOWN:
            instrument.color = clamp(instrument.color - 0.04, 0.0, 1.0)
        elif key == ord("["):
            instrument.pulse = clamp(instrument.pulse - 0.03, 0.05, 0.95)
        elif key == ord("]"):
            instrument.pulse = clamp(instrument.pulse + 0.03, 0.05, 0.95)
        elif key in (ord("a"), ord("A")):
            instrument.attack = clamp(instrument.attack + 0.004, 0.001, 0.20)
        elif key in (ord("z"), ord("Z")):
            instrument.attack = clamp(instrument.attack - 0.004, 0.001, 0.20)
        elif key in (ord("d"), ord("D")):
            instrument.decay = clamp(instrument.decay + 0.05, 0.05, 3.0)
        elif key in (ord("c"), ord("C")):
            instrument.decay = clamp(instrument.decay - 0.05, 0.05, 3.0)
        elif key in (ord("r"), ord("R")):
            self.forge_wave()
        elif key == ord(" "):
            self.core.audition(self.cursor_channel, self.selected_note())

    def handle_insert(self, key: int) -> bool:
        if key in (ord("i"), ord("I"), 27):
            self.insert_mode = False
            self.flash("NAVIGATE MODE")
            return True
        if ord("2") <= key <= ord("6"):
            self.octave = key - ord("0")
            self.flash(f"NOTE OCTAVE -> {self.octave}")
            return True
        if key in (curses.KEY_BACKSPACE, curses.KEY_DC, 8, 127):
            self.project.pattern[self.cursor_channel][self.cursor_row] = Step()
            return True
        try:
            character = chr(key).lower()
        except (ValueError, OverflowError):
            return False
        if character in NOTE_KEYS:
            note = 12 * (self.octave + 1) + NOTE_OFFSETS[NOTE_KEYS.index(character)]
            effect = "HIT" if self.cursor_channel in DRUM_CHANNELS else "MIN" if self.cursor_channel == 2 else "---"
            if self.cursor_channel in DRUM_CHANNELS:
                note = (36, 38, 42)[min(2, NOTE_KEYS.index(character) // 4)]
            self.project.pattern[self.cursor_channel][self.cursor_row] = Step(note, 13, effect)
            self.core.audition(self.cursor_channel, note)
            self.burst((3, 6, 2, 1, 4, 5)[self.cursor_channel], 8, 0.10 + self.cursor_channel * 0.16)
            self.cursor_row = (self.cursor_row + 1) % self.project.rows
            self.page = self.cursor_row // 16
            return True
        return False

    def keypress(self, key: int) -> None:
        if self.help:
            if key in (ord("h"), ord("H"), ord("q"), ord("Q"), 27):
                self.help = False
            return
        if self.wave_lab:
            self.handle_wave_lab(key)
            return
        if self.insert_mode and self.handle_insert(key):
            return
        if key in (ord("q"), ord("Q")):
            self.running = False
        elif key in (ord("h"), ord("H")):
            self.help = True
            self.burst(4, 18)
        elif key == ord(" "):
            self.core.toggle()
            self.flash("TRANSPORT PLAY" if self.core.playing else "TRANSPORT STOP")
        elif key in (ord("g"), ord("G")):
            self.core.stop()
            generate_song(self.project, self.style_index)
            self.core.reseed()
            self.cursor_row = self.page = 0
            self.core.start(0)
            self.burst(3, 42)
            self.flash(f"GENERATED {self.project.style} // SEED {self.project.seed}", 4.0)
        elif key in (ord("y"), ord("Y")):
            self.style_index = (self.style_index + 1) % len(STYLES)
            self.core.stop()
            generate_song(self.project, self.style_index)
            self.core.reseed()
            self.core.start(0)
            self.burst(2, 36)
            self.flash(f"STYLE -> {self.project.style}", 3.0)
        elif key in (ord("m"), ord("M")):
            changes = mutate_song(self.project)
            self.burst(5, 28)
            self.flash(f"MUTATION COMPLETE // {changes} MUSICAL CHANGES")
        elif key in (ord("i"), ord("I")):
            self.insert_mode = True
            self.burst(5, 14, 0.75)
            self.flash(f"INSERT MODE // OCTAVE {self.octave} // Z S X D C V G B H N J M ,")
        elif key in (ord("w"), ord("W")):
            self.wave_lab = True
            self.burst(2, 20, 0.75)
        elif key in (ord("s"), ord("S")):
            self.save()
        elif key in (ord("e"), ord("E")):
            self.export()
        elif key in (ord("c"), ord("C")):
            self.project.pattern[self.cursor_channel] = [Step() for _ in range(self.project.rows)]
            self.flash(f"CLEARED CHANNEL {self.cursor_channel + 1} {CHANNEL_NAMES[self.cursor_channel]}")
        elif key in (ord("+"), ord("=")):
            self.project.bpm = min(240, self.project.bpm + 2)
        elif key in (ord("-"), ord("_")):
            self.project.bpm = max(40, self.project.bpm - 2)
        elif key == ord("<"):
            self.project.swing = clamp(self.project.swing - 0.02, 0.0, 0.45)
        elif key == ord(">"):
            self.project.swing = clamp(self.project.swing + 0.02, 0.0, 0.45)
        elif key == 9:
            self.cursor_channel = (self.cursor_channel + 1) % CHANNEL_COUNT
        elif key == curses.KEY_LEFT:
            self.cursor_channel = (self.cursor_channel - 1) % CHANNEL_COUNT
        elif key == curses.KEY_RIGHT:
            self.cursor_channel = (self.cursor_channel + 1) % CHANNEL_COUNT
        elif key == curses.KEY_UP:
            self.cursor_row = (self.cursor_row - 1) % self.project.rows
            self.page = self.cursor_row // 16
        elif key == curses.KEY_DOWN:
            self.cursor_row = (self.cursor_row + 1) % self.project.rows
            self.page = self.cursor_row // 16
        elif key == ord("[") or key == curses.KEY_PPAGE:
            self.page = (self.page - 1) % 4
            self.cursor_row = self.page * 16 + self.cursor_row % 16
        elif key == ord("]") or key == curses.KEY_NPAGE:
            self.page = (self.page + 1) % 4
            self.cursor_row = self.page * 16 + self.cursor_row % 16
        elif key in (10, 13, curses.KEY_ENTER):
            self.core.audition(self.cursor_channel, self.selected_note())

    def run(self, screen: Any) -> int:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.nodelay(True)
        screen.keypad(True)
        curses.start_color()
        if curses.has_colors():
            background = -1
            try:
                curses.use_default_colors()
            except curses.error:
                background = curses.COLOR_BLACK
            colors = (curses.COLOR_CYAN, curses.COLOR_MAGENTA, curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_BLUE, curses.COLOR_WHITE)
            for index, color in enumerate(colors, 1):
                curses.init_pair(index, color, background)
                # Dedicated opaque popup palette. Pair 8..14 always uses black
                # even when the main tracker honors terminal transparency.
                curses.init_pair(index + 7, color, curses.COLOR_BLACK)
        self.output.start()
        try:
            while self.running:
                if self.output.no_audio and self.core.playing:
                    self.core.render(max(1, self.core.sample_rate // 30))
                key = screen.getch()
                if key != -1:
                    self.keypress(key)
                self.draw(screen)
                time.sleep(1 / 30)
            return 0
        finally:
            self.output.close()


def doctor(args: argparse.Namespace) -> int:
    print(f"{APP} {VERSION} — HARDWARE AUDIO CHECK\n")
    print(f"OK      Python               {sys.version.split()[0]}")
    print(f"OK      NumPy                {np.__version__}")
    try:
        import sounddevice as sd

        print(f"OK      sounddevice          {sd.__version__}")
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        outputs = []
        for index, item in enumerate(devices):
            if item["max_output_channels"] > 0:
                outputs.append((index, hostapis[item["hostapi"]]["name"], item["name"]))
        for index, host, name in outputs:
            print(f"OUTPUT  device {index:<4}         {host} :: {name}")
        if not outputs:
            print("ERROR   Audio output          no output devices found")
            return 2
    except Exception as exc:
        print(f"ERROR   sounddevice          {exc}")
        print("        Install requirements or use --no-audio for visual/edit/export mode.")
        return 2
    print("\nSignal path: tracker -> custom oscillator DSP -> signed 16-bit stereo PCM -> PortAudio host device")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atari-era six-lane CLI tracker with a raw-PCM waveform forge")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--project", type=Path, default=Path("projects/last_project.json"), help="project JSON path")
    parser.add_argument("--exports", type=Path, default=Path("exports"), help="production export directory")
    parser.add_argument("--sample-rate", type=int, default=44100)
    parser.add_argument("--device", help="PortAudio output device index or name")
    parser.add_argument("--latency", choices=("low", "high"), default="low")
    parser.add_argument("--style", type=int, choices=range(1, len(STYLES) + 1), default=1,
                        help=f"starter style 1..{len(STYLES)}")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--render", action="store_true", help="export without opening the tracker")
    parser.add_argument("--no-audio", action="store_true", help="edit and render without opening an audio device")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.doctor:
        return doctor(args)
    if args.project.exists():
        project = TrackerProject.load(args.project)
    else:
        project = TrackerProject()
        generate_song(project, args.style - 1, args.seed)
    if args.render:
        folder = export_project(project, args.exports, args.sample_rate)
        print(f"Export ready: {folder}")
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("error: CHIPFORGE ST needs a TTY; use --render for headless export", file=sys.stderr)
        return 2
    core = SynthCore(project, args.sample_rate)
    output = RawPCMOutput(core, args.device, args.latency, args.no_audio)
    ui = TrackerUI(project, core, output, args.project, args.exports)
    try:
        return curses.wrapper(ui.run)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
