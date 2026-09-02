# CHIPFORGE WORKSTATION

## 3.4.1 Vocal Word Pads

The three vocal-word controls are now full-size phrase pads instead of tiny
icon-width buttons. Each pad keeps its slot number, speaker glyph and complete
word visible, with a distinct empty `+ ADD` state and a larger click target.
The word engine, timing, Track 7 loop and saved-project format are unchanged.

## 3.4 Vocal Word Chooser

Track 7 now exposes one to three curated vocal-word slots. Click a filled slot
to cycle OH, AH, OOH, HEY, YEAH, YO, AY, UH, EE, EH and HA; the next empty slot
is an explicit `+ ADD`, and `REMOVE LAST` never allows an unusable zero-word
phrase. `RANDOMIZE WORDS` chooses a style-aware one-, two- or three-word hit.

One word produces the punchiest stab, two remains the musical default, and
three creates a compact chant. All short pad actions still occupy exactly one
beat, while HOLD remains two beats. Word selection is persisted and stays
locked when AUTO regenerates the sparse four-bar pad loop. Full song generation
may still propose a fresh word phrase. Old `OO` spellings upgrade to `OOH`, and
unsupported legacy free text falls back safely to `OH / AH`.

## Historical: 3.3.1 Soundboard UI

The Track 7 takeover now separates PLAY MODE, PERFORM and PROGRAM into visible
sections. Three direct mode buttons replace the ambiguous cycle control; VOICE
and BODY labels identify the two timbre selectors. The four-bar loop is drawn
as four labeled bar blocks with four large, icon-free beat cells each, removing
the clipped glyph/text collision seen in V3.3.0.

Tapping a performance pad both queues it and selects it for programming.
Clicking an empty beat adds that pad; clicking any filled beat removes it in one
step. Large performance pads, a clear playhead, explicit instructions and a
three-step guide make the soundboard usable without knowing tracker notation.

## Historical: 3.3 Track 7 Soundboard

V3.3 turns the generated VOX layer into a real seventh performance track. It
has eight live pads—STAB, DROP, CHOP, DIVE, THROW, HOLD, REPLY and WUB—and its
own sixteen-cell, four-bar loop. Every cell is beat-quantized by the same
sample clock as the six tracker lanes, so live playback, the master and
`stem_7_vox.wav` stay aligned at every tempo.

The soundboard is a third managed surface rather than a permanently cramped
third column. `7` opens its takeover; Escape returns to Split. The gold View
control cycles Split, Deck, Visual and Soundboard, while the compact Track 7
strip remains visible over the tracker.

OFF leaves only the live pads, LOOP repeats the player's fixed pattern, and
AUTO writes a new sparse one- or two-hit pattern only when the Song Map enters
a new four-bar scene. AUTO no longer injects an extra vocal at the boundary.
Selecting a pad and clicking a loop cell places or removes that sound; NEW
SPARSE LOOP and CLEAR LOOP make the state obvious.

WOBBLE, DEEP and MUTANT bodies add a phase-warped vowel oscillator, a stable
sub-octave fundamental, tempo-divided filter motion and dark saturation. The
result is lower, fatter experimental-bass punctuation while the six-lane song
engine remains unchanged. Older ASSIST projects migrate to a fixed LOOP.

## Historical: 3.2 VOX FX

V3.2 retires the attempted text-to-speech instrument. VOX is now a compact
musical-effects deck built from generated vowel spectra: no recordings,
soundbanks, speech process, browser, or model download. The additive oscillator
creates a stable pitched body first, then CHIPFORGE applies song tuning, rhythmic
gating, bend, crush and tempo delay.

`STAB` lands on the next beat. `DROP LOOP` starts a one-beat three-part pickup on
beat four and finishes exactly on the next downbeat every two bars. `CHOP`,
`BEND`, `THROW` and `HOLD` are beat-locked; `REPLY` uses the quietest coming lead
gap. Each gesture creates real negative space with action-specific smooth
ducking, with the drop pickup receiving the strongest foreground priority.

`NEW SHAPE` chooses one of six vowel palettes. SOUL, DEEP, CHOIR, RAVE and ROBOT
select the generated body; PUNCH, TUNE, CHOP and AIR select delivery. TUNE can
borrow the coming lead contour, while all other modes stay anchored to the
song's root and fifth. V3.0/V3.1 projects load safely: old character and mode
choices are mapped to their closest musical equivalent, and old free text is
not sent back through the failed speech renderer.

## Historical: 3.1 VOX Groove

VOX now measures phrases in beat fractions rather than free-running seconds.
Two syllables normally occupy one beat; longer calls may use two, while short
Hooks leave deliberate musical space instead of stretching words across a bar.
CALL and ANSWER inspect the coming lead lane and land in the quietest beat of
the next bar. MELODY borrows the actual lead contour, while every delivery mode
anchors its oscillator to a comfortable root/fifth register.

Generated language is deliberately compact and uses a fully curated phonetic
lexicon. Lexical stress, stop closures, release bursts and moving diphthongs
make the limited vocabulary more legible; arbitrary typed English remains an
experimental rule-based path. Ducking now follows a smooth attack/release
envelope, and the tempo delay is fed primarily by the final word instead of
smearing the entire phrase.

## Historical: 3.0.1 VOX Revoice

The first VOX renderer was stable but sounded wrong: hot parallel resonators,
per-phoneme hard gates and always-on damage reduced speech to choppy vowel
mush. 3.0.1 replaces that path with a normalized cascade vocal tract,
Rosenberg-style glottal excitation, differentiated frication, coarticulated
formant movement and controlled lip radiation. Word edges—not every phoneme—
carry the envelope. Clean speech is now the foundation; clock collapse,
formant swaps and bit damage enter only when BEND is performed.

Default Bend, Clock and Slap amounts are substantially lower. Existing deck,
PipeWire, tracker, Song Map, visualizer, persistence and export behavior is
otherwise unchanged.

## Historical: 3.0 VOX Deck

V3 adds a seventh internal performance layer without adding a seventh tracker
column. The VOX Deck turns generated text into phonemes and synthesizes every
sound from pulse/noise excitation, three stateful vocal-tract resonators,
envelopes, clock damage, saturation and tempo delay. There are no recorded
words, external speech processes, model downloads or audio loopbacks.

`CALL`, `CHOP`, `BEND`, `ECHO`, `FREEZE` and `ANSWER` land on beat boundaries.
`HOOK` lands on the next bar and repeats every two bars. SPELL, GIANT, GREMLIN,
CHOIR and TERMINAL voice bodies combine with CHANT, MELODY, RHYTHM and ORACLE
delivery modes. `V` fires a call and `B` bends the active voice when Insert mode
is off.

VOX automation is deliberately scarce. OFF is fully manual; ASSIST generates a
new line as the Song Map moves but waits for the player; AUTO performs only at
structural moments such as lifts, hooks, drops, climaxes and returns. The vocal
envelope applies restrained attack-only ducking to the music, appears on the
seventh hardware meter, enters the exact master PCM seen by the visualizer and
exports as `stem_7_vox.wav`. Schema-1 through schema-3 projects load with the
deck ready but silent.

## 2.7.1 Arranger UX

The thin Song Path strip is now a visual four-card `SONG MAP`. Every card shows
its plain-language role and chord progression; cyan means playing, green means
queued, and the active card carries a live within-bar progress line. The Path
button opens a six-option chooser explaining each complete arc instead of
cycling blindly.

Manual `CUE NEXT` and `RETURN HOME` actions now land on the next bar and show a
beat countdown, so a click always has immediate visible feedback. Clicking the
same cue again cancels it, and Return Home disables itself when it would do
nothing. `LOOP SCENE` pauses only automatic harmonic travel; manual cues remain
available.

The former Auto control is now `EVOLVE`: Path changes harmony and sections,
while Evolve changes drums, fills and melodic details inside the active scene.
Both layers share the Song Map, and enabling Evolve no longer rewinds the Path.
The formerly blind Style cycle is now an `ALL STYLES` chooser; the eight bank
buttons remain fast live shortcuts. Page navigation disables itself in Deck
view because all four pages are already visible.

## 2.7 Song Path

CHIPFORGE now turns each generated four-bar theme into an obvious sixteen-bar
journey. A bright `SONG PATH` performance strip offers six arcs—Loop, Lift,
Journey, Build, Verse/Hook and Dream—with a live `NOW A > B 3B` countdown.
Every path moves through four related harmonic scenes while retaining the
song's instruments, rhythm language and recognizable motif. `NEXT` and `HOME`
queue a scene exactly on the next four-bar boundary; `HOLD` loops the current
scene. Keyboard performers can use `P`, `N`, `O` and `T` respectively.

The scene change occurs inside the audio clock before row zero is triggered, so
kick, bass and chord arrive together without a partial first bar. Auto-mutate
adopts each active scene as its protected theme, allowing rhythmic and melodic
evolution without reverting the new harmony. Existing schema-1/2 projects,
state slots, manual tracker edits, styles, Flow controls, renderers and exports
remain compatible.

## 2.6.5 Live Set

Sound-changing performance controls now use a short audio-thread crossfade,
so Generate, Mutate, Style, quick-bank, arrangement, and state-load changes do
not hard-cut the output. The single-page tracker follows the sounding page;
Deck view remains a stable four-page map. Four new direct banks (Techno, House,
DnB, and Synthwave) join Chiptune, 808, Vapor, and Lo-Fi, backed by eight new
club-oriented style recipes.

Version 2 combines every CHIPFORGE ST music feature with a live visualizer in
one resizable graphical Linux app. The tracker/generator occupies one pane and
the visual instrument occupies the other; drag the divider or press `F6` to
switch keyboard focus smoothly.

Version 2.6 adds the Flow Generation Lab and a backward-compatible six-lane
engine. Randomness controls performance density and motif transformation while
remaining scale-bound; Music Math selects progressions by harmonic travel and
generates the correct diatonic chord quality, close chord movement and recurring
lead motifs. Any two style machines can be blended across tempo, swing, density,
key center and oscillator family. `4 CORE` preserves the classic Drum/Bass/Chord/
Lead arrangement; `6 FULL` adds deliberately quiet Perc and Air support lanes.
Old four-channel projects upgrade with both new lanes empty, so their mix is
unchanged.

Version 2.6.1 replaces the separate visual fullscreen window with one dependable
in-window view toggle: `SPLIT → DECK → VISUAL`. Deck takeover gives the tracker
the entire workspace and lays pages 1–4 out as a readable 2×2 grid; Visual
takeover gives the same space to the active visualizer without duplicating it.
`F6` swaps Deck and Visual while either has taken over. `F11` is restored to its
original job: fullscreen the whole application. Escape exits OS fullscreen,
then returns a takeover view to Split.

Version 2.6.2 normalizes Tk pane identifiers before switching views, fixing the
unhashable `Tcl_Obj` callback failure exposed by Python 3.14 and Tk 9.

Version 2.6.3 is the cherry release-candidate polish pass. The final 3D pixel
cherry-bomb headphone artwork is loaded as the live Tk window icon, embedded in
the frozen Linux executable and copied into the Steam depot. Every action button
now carries a font-independent pixel glyph rendered by Tk, so its icon cannot
turn into a missing emoji square on another platform. A permanent four-line
hotkey rail remains visible in Split, Deck, Visual and F11 fullscreen modes and
shows every global, music, tracker-edit and visual binding. Insert mode now gives
its documented piano row priority over overlapping command letters; press `I`
to return to command mode.

Version 2.6.4 replaces the initial in-memory XBM glyph encoding with direct Tk
`PhotoImage` pixels. This avoids the `format error in bitmap data` raised by
Python 3.14/Tk 9 while preserving the same platform-independent button artwork.

Version 2.5 adds six vaporwave and six lo-fi beat machines without replacing
any chiptune, wonky or 808 style. VHS Pad, Cassette Keys, Tape Flute and Mall
Bass are synthesized oscillators with slow envelopes, dark filtering, pitch
wear and tape dust. Dedicated CHIPTUNE, 808, VAPOR and LO-FI bank buttons jump
straight to each family. Vapor Sun, Tape Deck and Rain Glass expand the visual
bank alongside Vaporwave and Lo-Fi Tape looks plus reactive VHS and rain FX.
Choosing a new tape-era music bank stages its matching visual automatically;
the clean master-PCM oscilloscope remains the untouched default.

Version 2.5.1 adds theme-locked endless variation. The `AUTO` control cycles
between off and changes every 4, 8 or 16 bars, with a live bar countdown. Each
variation is rebuilt from a frozen primary theme at a pattern boundary: core
drum accents, bass roots, chord downbeats and opening motifs stay locked while
hats, pickups, chord answers and lead phrases evolve. Variation eight returns
to the exact original theme, so long playback has an arc but never drifts into
random note soup. Pressing Generate, manual Mutate or editing the tracker
establishes a new primary theme.

Version 2.4 adds eight dedicated 808/hip-hop style machines, five low-heavy
oscillators, pitched long-tail kick synthesis, sampler dust, and exposed Boom
and Dust controls. The synthesized kit now includes kick, rim, snare, clap,
closed/open hats and cowbell. Existing styles remain available, but every generator now
runs warmer and darker; bright edges acquire controlled pre-filter dirt instead
of exposed shrillness. The default visual is a triggered, gridded oscilloscope
fed by the exact master PCM, while every elaborate scene remains one click away.

Version 2.3 revoices the entire instrument around rounder, fatter defaults.
Every channel now has stateful low-pass tone shaping and soft warmth; generated
patches use restrained cutoff, drive and modulation ranges. Round, Velvet,
Rubber, Dubsub and Hollow join the wonky oscillators without sacrificing weight.
The GUI now saves and loads complete projects through state slots 0–9, shows an
explicit page number, and exports one master WAV through a normal file dialog.
Version 2.3.4 also makes the native PipeWire ring apply real backpressure, paces
the musical clock independently at the selected sample rate, guards live tempo
changes, and pins predictable DejaVu Sans Mono metrics under bundled Tk 9.

Audio is now **PipeWire native**. CHIPFORGE writes its synthesized signed PCM
directly to `pw-cat`, and the visualizer consumes that exact same stream. There
is no loopback setup, PortAudio layer, or device selection required.

## Quick start

Install PipeWire's command-line tools and Tk first. For Arch/Manjaro:

```bash
sudo pacman -S pipewire pipewire-audio tk
```

For Debian/Ubuntu:

```bash
sudo apt install pipewire-bin python3-tk
```

Then run:

```bash
./run.sh
```

## Steam distribution

`STEAM_ALPHA.md` and the `steam/` directory contain the self-contained Linux
depot builder, bundled native PipeWire bridge, launch wrapper and SteamPipe VDF
templates. AppID and DepotID remain explicit placeholders until Steam assigns
the real values.

The graphical app includes Generate, a quantized Track 7 soundboard, six Song Paths with quantized scene control, Flow Lab, cross-style blend, Music Math,
bounded randomness, 4 Core/6 Full arrangement, Style, Mutate, transport, editable tracker,
note insertion, tempo/swing, waveform forge, audition, save, WAV/stem/MIDI/JSON
export, ten visual engines, six looks, seven GPU-style compositing layers,
8-bit mode, visual mutation, Split/Deck/Visual/Soundboard takeover, HUD and FPS display. `F6` changes which
half receives the keyboard or swaps takeover views; `F11` toggles whole-app fullscreen. Headless production export
remains available with `./run.sh --render`, and `./run.sh --doctor` checks Tk and
PipeWire. The original terminal UI remains available in visual/no-audio mode
with `./run.sh --legacy --no-audio`; install `sounddevice` separately only if
you specifically want its old PortAudio output path.

The complete graphical hotkey map is always visible in the bottom rail. Button
icons are native pixel images rather than Unicode emoji, and the app
icon lives at `assets/chipforge-icon.png`; the Steam builder includes both in
the standalone distribution automatically.

---

## CHIPFORGE ST 1.3 reference

CHIPFORGE ST is a six-lane, Atari-era terminal tracker with a custom real-time synthesizer, waveform forge, oscilloscope, one-key song generator, editable note grid, and production export. Drum, Bass, Chord and Lead remain its four-channel core; Perc and Air are optional arrangement lanes.

Version 1.1 added an opaque-black popup system, a persistent mode beacon, context-sensitive control strips, animated beat lamps, live voice meters, moving raster rails, phosphor scope trails, and note/event particle bursts. The motion follows transport and voice state; it is not a disconnected screensaver.

It does **not** play a folder of samples. The tracker schedules notes; CHIPFORGE calculates each oscillator and drum sample; NumPy builds signed 16-bit stereo PCM; and `sounddevice` sends those bytes to the selected PortAudio device. On Linux that normally means ALSA or PipeWire. The same synthesis path renders the exported files.

No model, browser, DAW, or music theory is needed.

## Install

Linux needs PortAudio available to Python. On Arch/Manjaro:

```bash
sudo pacman -S portaudio
```

On Debian/Ubuntu:

```bash
sudo apt install libportaudio2
```

Then:

```bash
cd chipforge-st
python -m venv env
source env/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python chipforge_st.py --doctor
python chipforge_st.py
```

Use a terminal at least 100 columns by 30 rows. Larger is better.

## The five-second path

1. Press `G` to make a complete four-bar theme; the default Lift path begins running.
2. Press `Space` to stop or restart it.
3. Press `M` to create a related musical mutation.
4. Press `Y` to move through all 28 style machines.
5. Press `P` to choose a Song Path and `N` to cue its next harmonic scene.
6. Press `E` to export the active scene for a DAW.

The generated pattern is constrained to a scale and coherent chord progression. Randomness changes the performance without becoming arbitrary note soup.

## Main controls

| Key | Action |
| --- | --- |
| `G` | Generate a complete song in the current style |
| `Y` | Open the complete thirty-six-style chooser |
| `M` | Mutate the current song while preserving its musical frame |
| `A` | Evolve performance details: off, then every 4, 8 or 16 bars |
| `P` | Open the visual Song Path chooser |
| `N` | Cue the next harmonic scene on the next bar; press again to cancel |
| `O` | Return Home—or to the path's opening scene—on the next bar |
| `T` | Loop the current scene/resume the complete Path |
| `Space` | Start/stop the sample-accurate tracker transport |
| Arrow keys | Move through rows and channels |
| `[` / `]` | Move between the four 16-row pages |
| `Tab` | Select next channel |
| `I` | Enter/leave note-insert mode |
| `W` | Open waveform forge for the selected channel |
| `+` / `-` | Change tempo |
| `<` / `>` | Change swing |
| `C` | Clear selected channel |
| `S` | Save the editable tracker project |
| `E` | Export master, stems, MIDI, and project JSON |
| `H` | Full control overlay |
| `Q` | Quit |

## Note entry without a MIDI keyboard

Select a channel and press `I`. The bottom computer-keyboard row becomes a chromatic piano:

```text
Z S X D C V G B H N J M ,
C   D   E F   G   A   B C
```

Press `2` through `6` to select the octave. Each entered note advances the tracker row. Backspace/Delete clears a row. Press `I` or Escape to return to navigation.

On the drum channel, the same keys choose kick, snare, and hi-hat regions automatically.

## Waveform forge

Press `W` on BASS, CHORD, or LEAD to design the actual oscillator:

- Left/right: sine, square, saw, triangle, pulse, organ, FM, ring modulation, metal, or noise.
- Up/down: alter waveform color/modulation depth.
- `[`/`]`: change pulse width.
- `A`/`Z`: attack.
- `D`/`C`: decay.
- `R`: forge a randomized waveform and envelope.
- Space: audition.
- Enter or `W`: return to the tracker.

The upper oscilloscope shows the computed signal, not decorative animation.

## Knowing what mode you are in

The upper-right badge and lower control strip always identify the active mode:

- `NAVIGATE`: arrows move around the tracker; the global commands are active.
- `INSERT O3`: the keyboard is a piano and the badge includes the current octave.
- `WAVE FORGE`: controls edit the selected oscillator; Enter, `W`, or Escape exits.
- `HELP`: `H`, `Q`, or Escape returns to the tracker without quitting the program.

Help and Waveform Forge use their own opaque black terminal palette, so the moving tracker and oscilloscope cannot bleed through the popup on transparent terminal themes.

## Styles

- Eight original chiptune/electronic machines, from Neon Noir through Cosmic Sludge.
- Eight dedicated 808/hip-hop machines, from 808 Boom Bap through Lowrider Sunset.
- Six vaporwave machines: Mall After Midnight, VHS Palms, Plaza Elevator, Empty Food Court, Windows 95 Sunset and Neon Aquarium.
- Six lo-fi machines: Rainy Window Beats, Study Tape 1998, Bedroom Cassette, Sunday Vinyl, Late Night Homework and Coffee Shop Loop.

Each changes tempo, swing, density, root, oscillator family, envelope, pulse width, modulation color and rhythm logic.

## Production output

Press `E`. Each session receives its own directory under `exports/`:

```text
exports/20260824-220000-neon-noir/
├── master.wav
├── stem_1_drum.wav
├── stem_2_bass.wav
├── stem_3_chord.wav
├── stem_4_lead.wav
├── stem_5_perc.wav
├── stem_6_air.wav
├── stem_7_vox.wav
├── pattern.mid
└── project.json
```

All WAVs are stereo 16-bit PCM at the configured sample rate and exactly one 64-row/four-bar tracker cycle long. The seven stems start at the same sample and can be dropped directly into a DAW. `pattern.mid` carries the six tracker lanes; the backward-compatible `stem_7_vox.wav` filename carries the generated Track 7 soundboard loop. `project.json` preserves every synth, tracker, Flow Lab and soundboard parameter.

Headless export is also available:

```bash
python chipforge_st.py --project projects/last_project.json --render
```

Choose a specific hardware output:

```bash
python chipforge_st.py --doctor
python chipforge_st.py --device 3 --latency low
```

Visual/edit/export mode without an audio device:

```bash
python chipforge_st.py --no-audio
```

## Why this feels immediate

Music-generation models render recordings and therefore introduce seconds of latency. CHIPFORGE instead performs synthesis inside a continuous PCM callback. The tracker clock, oscillators, additive vowel spectra, envelopes, drum synthesis, panning, swing, and export renderer all live in this project.

This is the correct foundation for later raw `/dev/input` Guitar Hero controllers, MIDI input, joystick mapping, external clock, or direct ALSA experiments because performance events are already separated from the audio renderer.

## Tests

```bash
python tests/smoke_test.py
```

The test requires no sound card. It validates generation, mutation, synthesis, procedural VOX FX, legacy upgrades, deterministic project persistence, master/stem alignment, WAV headers, MIDI creation, and headless rendering.
