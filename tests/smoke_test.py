#!/usr/bin/env python3
"""No-sound-card verification for CHIPFORGE ST."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import wave

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chipforge_st import (  # noqa: E402
    CHANNEL_COUNT,
    CHANNEL_NAMES,
    RawPCMOutput,
    STYLES,
    SynthCore,
    TrackerUI,
    TrackerProject,
    export_project,
    generate_song,
    mutate_song,
    render_project,
)


def main() -> int:
    project = TrackerProject()
    generate_song(project, 0, seed=424242)
    assert project.style == STYLES[0]["name"]
    assert len(project.pattern) == CHANNEL_COUNT
    assert all(len(channel) == 64 for channel in project.pattern)
    assert all(any(step.note is not None for step in channel) for channel in project.pattern[:4])
    assert all(step.note is None for channel in project.pattern[4:] for step in channel)

    before = json.dumps(project.to_dict(), sort_keys=True)
    changes = mutate_song(project, amount=0.8, seed=7)
    after = json.dumps(project.to_dict(), sort_keys=True)
    assert changes > 0 and before != after

    core = SynthCore(project.clone(), sample_rate=22050)
    core.start()
    audio = core.render(8192)
    assert audio.shape == (8192, 2)
    assert np.isfinite(audio).all()
    assert float(np.max(np.abs(audio))) > 0.001
    core.stop()
    core.audition(3, 64)
    audition = core.render(2048)
    assert float(np.max(np.abs(audition))) > 0.001
    assert len(core.activity_levels()) == CHANNEL_COUNT

    ui = TrackerUI(project, core, RawPCMOutput(core, no_audio=True), Path("project.json"), Path("exports"))
    assert ui.mode_name() == "NAVIGATE"
    ui.insert_mode = True
    assert ui.mode_name() == "INSERT O3"
    ui.wave_lab = True
    assert ui.mode_name() == "WAVE FORGE"
    ui.help = True
    assert ui.mode_name() == "HELP"
    ui.burst(3, 12)
    assert len(ui.sparks) == 12
    ui.tick_fx()

    with tempfile.TemporaryDirectory(prefix="chipforge-test-") as temporary:
        root = Path(temporary)
        project_path = root / "project.json"
        project.save(project_path)
        loaded = TrackerProject.load(project_path)
        assert loaded.to_dict() == project.to_dict()

        rendered = render_project(project, 22050)
        expected = sum(SynthCore(project, 22050).row_samples(row) for row in range(project.rows))
        assert rendered.shape == (expected, 2)

        folder = export_project(project, root / "exports", sample_rate=22050)
        expected_files = {
            "master.wav",
            "pattern.mid",
            "project.json",
            *(f"stem_{index + 1}_{name.lower()}.wav" for index, name in enumerate(CHANNEL_NAMES)),
        }
        assert expected_files == {path.name for path in folder.iterdir()}
        for filename in ("master.wav", *(f"stem_{index + 1}_{name.lower()}.wav" for index, name in enumerate(CHANNEL_NAMES))):
            with wave.open(str(folder / filename), "rb") as source:
                assert source.getnchannels() == 2
                assert source.getsampwidth() == 2
                assert source.getframerate() == 22050
                assert source.getnframes() == expected
        midi = (folder / "pattern.mid").read_bytes()
        assert midi.startswith(b"MThd") and midi.count(b"MTrk") == CHANNEL_COUNT + 1

    print("CHIPFORGE ST smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
