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
    VOX_CHANNEL,
    export_project,
    generate_song,
    generate_vox_phrase,
    mutate_song,
    parse_vox_words,
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
    assert len(core.activity_levels()) == CHANNEL_COUNT + 1

    # The V3.4 layer is a pitched bass effect, not synthetic speech. Default
    # damage is low, CALL deliberately contains rhythmic space, and WUB/BEND
    # are materially different gestures rather than the idle sound.
    fx_project = TrackerProject();fx_project.vox.phrase = "AH / OH"
    assert fx_project.vox.bend <= .10 and fx_project.vox.clock <= .05
    clean_vox = SynthCore(fx_project, sample_rate=22050, solo=VOX_CHANNEL)
    clean_vox.fire_vox("CALL");clean_stab = clean_vox.render(22050).mean(axis=1)
    blocks = clean_stab[:len(clean_stab)//128*128].reshape(-1,128)
    rms = np.sqrt(np.mean(blocks**2, axis=1));active = np.flatnonzero(rms > 1e-4)
    assert len(active) > 20 and np.any(rms[active[0]:active[-1]+1] < 1e-4)
    bent_vox = SynthCore(fx_project.clone(), sample_rate=22050, solo=VOX_CHANNEL)
    bent_vox.fire_vox("BEND");bent_stab = bent_vox.render(22050).mean(axis=1)
    assert not np.array_equal(clean_stab, bent_stab)
    wub_vox = SynthCore(fx_project.clone(), sample_rate=22050, solo=VOX_CHANNEL)
    wub_vox.fire_vox("WUB");wub = wub_vox.render(22050).mean(axis=1)
    spectrum = np.abs(np.fft.rfft(wub));frequencies=np.fft.rfftfreq(len(wub),1/22050)
    assert spectrum[frequencies < 180].sum() > spectrum[(frequencies >= 180) & (frequencies < 2000)].sum() * .08
    # Every short FX gesture owns exactly one beat at every tempo; HOLD owns two.
    windows = []
    for tempo in (80, 140):
        timed = TrackerProject(bpm=tempo);timed.vox.phrase="OH / HEY"
        timed_core = SynthCore(timed, sample_rate=22050, solo=VOX_CHANNEL);timed_core.fire_vox("CALL")
        frames = sum(segment.samples for segment in timed_core.vox.segments)
        assert frames == timed_core.vox.target_samples and timed_core.vox.speech_beats == 1.0
        windows.append(frames)
        hold_core = SynthCore(timed, sample_rate=22050, solo=VOX_CHANNEL);hold_core.fire_vox("FREEZE")
        assert sum(segment.samples for segment in hold_core.vox.segments) == int(round(22050*60/tempo*2))
    assert windows[0] > windows[1]
    # Curated phrases accept one, two or three visible words while every short
    # pad still owns exactly one beat. Old OO spelling migrates to OOH.
    for phrase,count in (("OH",1),("OH / AH",2),("OH / AH / HEY",3)):
        phrase_project=TrackerProject(bpm=118);phrase_project.vox.phrase=phrase
        phrase_core=SynthCore(phrase_project,sample_rate=22050,solo=VOX_CHANNEL);phrase_core.fire_vox("CALL")
        assert phrase_core.vox.speech_beats==1.0
        assert len({segment.phoneme for segment in phrase_core.vox.segments if segment.phoneme!="SP"})<=count
    assert parse_vox_words("OO / AH / YO / HEY")==["OOH","AH","YO"]
    generated_words=parse_vox_words(generate_vox_phrase(project,9))
    assert 1<=len(generated_words)<=3

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

        # Schema-3 projects had no VOX object. They still load silently and
        # remain silent until the performer fires the deck.
        legacy = project.to_dict(); legacy.pop("vox"); legacy["schema"] = 3
        upgraded = TrackerProject.from_dict(legacy)
        assert upgraded.vox.phrase == "OH / AH" and not upgraded.vox.hook
        legacy_words=project.to_dict();legacy_words["vox"]["phrase"]="OO / AH / YO / HEY"
        assert TrackerProject.from_dict(legacy_words).vox.phrase=="OOH / AH / YO"
        bad_v3 = project.to_dict();bad_v3["version"] = "3.0.0"
        bad_v3["vox"].update({"bend":.36,"clock":.18,"slap":.58})
        migrated = TrackerProject.from_dict(bad_v3)
        assert (migrated.vox.bend,migrated.vox.clock,migrated.vox.slap)==(.06,.02,.24)
        old_assist=project.to_dict();old_assist["vox"]["automation"]="ASSIST";old_assist["vox"].pop("loop")
        loop_upgrade=TrackerProject.from_dict(old_assist)
        assert loop_upgrade.vox.automation=="LOOP" and len(loop_upgrade.vox.loop)==16

        project.vox.automation="LOOP";project.vox.loop=["CALL"]+["---"]*15
        vocal = render_project(project, 22050, solo=VOX_CHANNEL)
        assert np.isfinite(vocal).all() and float(np.max(np.abs(vocal))) > .01

        rendered = render_project(project, 22050)
        expected = sum(SynthCore(project, 22050).row_samples(row) for row in range(project.rows))
        assert rendered.shape == (expected, 2)

        folder = export_project(project, root / "exports", sample_rate=22050)
        expected_files = {
            "master.wav",
            "pattern.mid",
            "project.json",
            *(f"stem_{index + 1}_{name.lower()}.wav" for index, name in enumerate(CHANNEL_NAMES)),
            "stem_7_vox.wav",
        }
        assert expected_files == {path.name for path in folder.iterdir()}
        for filename in ("master.wav", *(f"stem_{index + 1}_{name.lower()}.wav" for index, name in enumerate(CHANNEL_NAMES)), "stem_7_vox.wav"):
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
