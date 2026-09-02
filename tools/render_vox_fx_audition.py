#!/usr/bin/env python3
"""Render V3.4 one/two/three-word pads, then Track 7 in context."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chipforge_st import (STYLES, SynthCore, TrackerProject, VOX_CHANNEL,
                          generate_song, write_wav)  # noqa: E402


def fade(audio: np.ndarray, sample_rate: int, milliseconds: float = 12.0) -> np.ndarray:
    result = audio.copy()
    count = min(len(result) // 2, max(1, int(sample_rate * milliseconds / 1000.0)))
    ramp = np.linspace(0.0, 1.0, count, dtype=np.float32)
    result[:count] *= ramp[:, None]
    result[-count:] *= ramp[::-1, None]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--sample-rate", type=int, default=44100)
    args = parser.parse_args()

    style_index = next(index for index, style in enumerate(STYLES) if style["name"] == "WAREHOUSE PULSE")
    project = TrackerProject(bpm=128, seed=320, track_count=6)
    generate_song(project, style_index, seed=320)
    project.vox.voice = "WOBBLE"
    project.vox.mode = "PUNCH"
    project.vox.phrase = "OH / HEY"

    beat_frames = int(round(args.sample_rate * 60.0 / project.bpm))
    pad_renders=[]
    for voice,action,phrase in (("WOBBLE","CALL","OH"),("MUTANT","HOOK","OH / AH"),
                                ("DEEP","BEND","OOH / YO / HEY"),("WOBBLE","CHOP","AH / YEAH / OH")):
        pad_project=project.clone();pad_project.vox.voice=voice;pad_project.vox.phrase=phrase
        dry_core=SynthCore(pad_project,args.sample_rate,solo=VOX_CHANNEL);dry_core.fire_vox(action)
        pad_renders.append(fade(dry_core.render(int(beat_frames*1.55)),args.sample_rate))

    silence = np.zeros((int(args.sample_rate * .26), 2), dtype=np.float32)
    dry=np.concatenate([item for pad in pad_renders for item in (pad,silence)],axis=0)
    context_project = project.clone();context_project.vox.automation="LOOP";context_project.vox.phrase="OH / AH / HEY"
    context_project.vox.loop=["---"]*16;context_project.vox.loop[6]="WUB";context_project.vox.loop[14]="HOOK"
    context_core = SynthCore(context_project, args.sample_rate)
    context_core.start(0)
    context_frames = sum(context_core.row_samples(row) for row in range(context_project.rows))
    context = context_core.render(context_frames)

    audition = np.concatenate((fade(dry, args.sample_rate), silence, fade(context, args.sample_rate)), axis=0)
    peak = float(np.max(np.abs(audition)))
    if peak > 0.0:
        audition *= .90 / peak
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_wav(args.output, audition, args.sample_rate)
    print(f"wrote {args.output} ({len(audition)/args.sample_rate:.2f}s, peak={float(np.max(np.abs(audition))):.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
