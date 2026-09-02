#!/usr/bin/env python3
"""Round-trip persistence, wonky DSP and production export regression test."""
from pathlib import Path
import json
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chipforge_st import (CHANNEL_COUNT, CHANNEL_NAMES, LOFI_STYLE_NAMES, PROGRESSIONS, SCALE_MODES, STYLES,
                          VAPORWAVE_STYLE_NAMES, WAVEFORMS, SynthCore, TrackerProject, chord_intervals,
                          export_project, generate_song, render_project, theme_variation, write_wav)

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    project = TrackerProject()
    wonky_style = next(i for i, style in enumerate(STYLES) if style["name"] == "SWAMP CIRCUIT")
    generate_song(project, wonky_style, seed=0xB055)
    project.instruments[1].waveform = "GROWL"
    project.instruments[1].wobble = .83
    project.instruments[1].drive = .61
    project.instruments[1].sub = .37
    project.instruments[0].boom = .91
    project.instruments[2].dust = .22
    saved = root / "wonky.json"
    project.save(saved)
    loaded = TrackerProject.load(saved)
    assert loaded.to_dict() == project.to_dict()
    assert loaded.instruments[1].wobble == .83
    assert loaded.instruments[0].boom == .91
    assert loaded.instruments[2].dust == .22

    # Every oscillator must render finite audio through the exact production DSP.
    for waveform in WAVEFORMS:
        loaded.instruments[1].waveform = waveform
        core = SynthCore(loaded.clone())
        core.start(0)
        audio = core.render(4096)
        assert audio.shape == (4096, 2)
        assert np.isfinite(audio).all(), waveform
        assert np.max(np.abs(audio)) <= 1.00001, waveform

    loaded.instruments[1].waveform = "WOBBLE"
    output = export_project(loaded, root / "exports")
    expected = {"master.wav", "pattern.mid", "project.json",
                *(f"stem_{index + 1}_{name.lower()}.wav" for index, name in enumerate(CHANNEL_NAMES)),
                "stem_7_vox.wav"}
    assert {item.name for item in output.iterdir()} == expected
    exported = TrackerProject.from_dict(json.loads((output / "project.json").read_text()))
    assert exported.to_dict() == loaded.to_dict()

    # The simplified GUI export uses this exact single-master path.
    single = root / "chosen-name.wav"
    write_wav(single, render_project(loaded, 44100), 44100)
    assert single.read_bytes()[:4] == b"RIFF"
    assert single.stat().st_size > 100_000

    # Retail defaults and every generated channel are intentionally warm.
    defaults = TrackerProject()
    assert defaults.instruments[1].waveform == "ROUND"
    assert defaults.instruments[1].cutoff <= 1800
    assert defaults.instruments[1].sub >= .20
    generated = TrackerProject(); generate_song(generated, 0, seed=99)
    assert all(200 <= item.cutoff <= 8500 for item in generated.instruments)
    assert all(item.warmth >= .30 for item in generated.instruments)

    # Dedicated 808 styles remain sub-first and dark instead of relabeling a
    # bright oscillator. Their bass render must carry far more lows than highs.
    hiphop_style = next(i for i, style in enumerate(STYLES) if style["name"] == "808 BOOM BAP")
    eight08 = TrackerProject(); generate_song(eight08, hiphop_style, seed=808)
    assert eight08.instruments[0].boom >= .78
    assert eight08.instruments[1].sub >= .34
    assert eight08.instruments[1].cutoff <= 1350
    bass_core = SynthCore(eight08, solo=1); bass_core.start(0)
    bass = bass_core.render(16384).mean(axis=1)
    spectrum = np.abs(np.fft.rfft(bass*np.hanning(len(bass))))
    frequencies = np.fft.rfftfreq(len(bass), 1/44100)
    assert spectrum[frequencies < 300].sum() > spectrum[frequencies > 3000].sum()*5

    # Every original style remains in its original slot; the new bank is added
    # after it rather than replacing the chiptune or 808 machines.
    original_styles = (
        "NEON NOIR", "DESERT DRIVE", "CATHEDRAL CIRCUIT", "ARCADE PANIC", "MIDNIGHT FUNK",
        "SWAMP CIRCUIT", "MUTANT MARSH", "COSMIC SLUDGE", "808 BOOM BAP", "TRUNK RATTLE",
        "GOLDEN ERA DUST", "SOUTH SIDE 808", "NIGHT BUS BASS", "CRATE DIGGER", "MEMPHIS TAPE",
        "LOWRIDER SUNSET",
    )
    assert tuple(style["name"] for style in STYLES[:len(original_styles)]) == original_styles
    assert len(VAPORWAVE_STYLE_NAMES) == 6
    assert len(LOFI_STYLE_NAMES) == 6

    # Bank changes are isolated: visiting a long-envelope vapor patch cannot
    # contaminate a later original preset.
    bank_switch = TrackerProject()
    vapor_index = next(i for i, item in enumerate(STYLES) if item["name"] == "MALL AFTER MIDNIGHT")
    generate_song(bank_switch, vapor_index, seed=123)
    generate_song(bank_switch, 0, seed=456)
    clean_original = TrackerProject(); generate_song(clean_original, 0, seed=456)
    assert bank_switch.to_dict() == clean_original.to_dict()

    # Tape-era presets are actual sound designs and pattern families: vaporwave
    # uses long blurred pads; lo-fi uses dusty, dark keys and pronounced swing.
    for style_name in sorted(VAPORWAVE_STYLE_NAMES):
        style_index = next(i for i, item in enumerate(STYLES) if item["name"] == style_name)
        vapor = TrackerProject(); generate_song(vapor, style_index, seed=0x5653)
        assert vapor.instruments[2].waveform in {"VHS PAD", "CASSETTE KEYS"}
        assert vapor.instruments[2].attack >= .10
        assert vapor.instruments[2].decay >= 2.10
        assert vapor.instruments[2].cutoff <= 2050
        rendered = SynthCore(vapor); rendered.start(0)
        assert np.max(np.abs(rendered.render(4096))) > .001
    for style_name in sorted(LOFI_STYLE_NAMES):
        style_index = next(i for i, item in enumerate(STYLES) if item["name"] == style_name)
        beat = TrackerProject(); generate_song(beat, style_index, seed=0x10F1)
        assert beat.swing >= .17
        assert beat.instruments[0].dust >= .18
        assert beat.instruments[2].dust >= .18
        assert beat.instruments[2].cutoff <= 1850
        rendered = SynthCore(beat); rendered.start(0)
        assert np.max(np.abs(rendered.render(4096))) > .001

    # Endless variation always branches from one immutable theme. Structural
    # downbeats stay exact, two calls with the same generation are identical,
    # and the eighth step returns completely home instead of accumulating drift.
    theme = TrackerProject(); generate_song(theme, vapor_index, seed=0xC0FFEE)
    variation = theme.clone(); changed = theme_variation(variation, theme, 3)
    assert changed > 0
    assert variation.instruments == theme.instruments
    for row in range(theme.rows):
        pos = row % 16
        if pos in (0, 4, 8, 12):
            assert variation.pattern[0][row] == theme.pattern[0][row]
        if pos == 0:
            assert variation.pattern[1][row] == theme.pattern[1][row]
            assert variation.pattern[2][row] == theme.pattern[2][row]
            assert variation.pattern[3][row] == theme.pattern[3][row]
    repeated = variation.clone(); theme_variation(repeated, theme, 3)
    assert repeated.pattern == variation.pattern
    total_cells = CHANNEL_COUNT*theme.rows
    different = sum(a != b for channel_a, channel_b in zip(variation.pattern, theme.pattern)
                    for a, b in zip(channel_a, channel_b))
    assert 0 < different < total_cells*.25
    theme_variation(variation, theme, 8)
    assert variation.pattern == theme.pattern

    # The expanded 808 kit is synthesized, editable, and audible without any
    # external sample files: kick, rim, snare, clap, hats and cowbell.
    for note in (36, 37, 38, 39, 42, 46, 56):
        drum_core = SynthCore(TrackerProject(), solo=0)
        drum_core.audition(0, note)
        hit = drum_core.render(4096)
        assert np.isfinite(hit).all() and np.max(np.abs(hit)) > .001, note
    tail_core = SynthCore(TrackerProject(), solo=0)
    tail_core.audition(0, 36)
    long_kick = tail_core.render(44100).mean(axis=1)
    assert np.sqrt(np.mean(long_kick[-4096:]**2)) > .01

    # Live tempo edits may shorten the row below its already-consumed position.
    # Rendering must advance safely, never request a negative NumPy dimension.
    tempo_core = SynthCore(generated)
    tempo_core.start(0)
    tempo_core.render(tempo_core.row_samples(0) - 8)
    generated.bpm = 240
    changed = tempo_core.render(1024)
    assert changed.shape == (1024, 2)

    # The transport exposes exact four-bar boundaries to the GUI timer.
    cycle_project = TrackerProject(); generate_song(cycle_project, 0, seed=12)
    cycle_core = SynthCore(cycle_project, sample_rate=4000); cycle_core.start(0)
    cycle_frames = sum(cycle_core.row_samples(row) for row in range(cycle_project.rows))
    cycle_core.render(cycle_frames)
    assert cycle_core.completed_cycles == 1
    assert cycle_core.current_row == 0
    cycle_core.toggle();cycle_core.toggle()
    assert cycle_core.completed_cycles == 1

    # Flow generation is deterministic, scale-bounded and optionally expands
    # to two restrained arrangement lanes without changing the four core roles.
    flow = TrackerProject(randomness=.82, harmonic_motion=.76, track_count=6,
                          blend_style="MALL AFTER MIDNIGHT", blend_amount=.45)
    generate_song(flow, hiphop_style, seed=2606, track_count=6)
    repeated_flow = TrackerProject(randomness=.82, harmonic_motion=.76, track_count=6,
                                   blend_style="MALL AFTER MIDNIGHT", blend_amount=.45)
    generate_song(repeated_flow, hiphop_style, seed=2606, track_count=6)
    assert flow.to_dict() == repeated_flow.to_dict()
    assert flow.progression in {item[0] for item in PROGRESSIONS}
    assert flow.mode in SCALE_MODES
    assert all(any(step.note is not None for step in channel) for channel in flow.pattern)
    assert max(item.volume for item in flow.instruments[4:]) < min(item.volume for item in flow.instruments[:2])
    four_core = TrackerProject(randomness=.82, harmonic_motion=.76, track_count=4,
                               blend_style="MALL AFTER MIDNIGHT", blend_amount=.45)
    generate_song(four_core, hiphop_style, seed=2606, track_count=4)
    assert four_core.pattern[:4] == flow.pattern[:4]
    assert all(step.note is None for channel in four_core.pattern[4:] for step in channel)
    flow_core = SynthCore(flow);flow_core.start(0);flow_audio = flow_core.render(8192)
    assert np.isfinite(flow_audio).all() and np.max(np.abs(flow_audio)) <= 1.00001
    for step in flow.pattern[2]:
        if step.note is not None:
            assert len(chord_intervals(step.effect)) >= 3

    # A schema-1 four-channel save upgrades silently and remains four-core:
    # the new lanes exist but are empty, so its original mix cannot change.
    legacy_data = flow.to_dict();legacy_data["schema"] = 1
    legacy_data.pop("track_count", None);legacy_data["instruments"] = legacy_data["instruments"][:4]
    legacy_data["pattern"] = legacy_data["pattern"][:4]
    legacy = TrackerProject.from_dict(legacy_data)
    assert legacy.track_count == 4 and len(legacy.pattern) == CHANNEL_COUNT
    assert all(step.note is None for channel in legacy.pattern[4:] for step in channel)

print("CHIPFORGE persistence/wonky/export test: PASS")
