# CHIPFORGE Steam Linux Alpha

This kit creates a self-contained Steam depot. Customers do not run `pip`, create
a virtual environment, or install `pw-cat`. The build compiles CHIPFORGE's small
PipeWire playback bridge and freezes Python, NumPy and Tk into the application.

## Build host dependencies

Arch/Manjaro:

```bash
sudo pacman -S --needed base-devel python tk pipewire-audio uv
```

Ubuntu/Debian:

```bash
sudo apt install build-essential python3 python3-venv python3-dev python3-tk libpipewire-0.3-dev pkg-config
```

Build:

```bash
./steam/build_steam_linux.sh
./steam-depot/CHIPFORGE/launch.sh
```

The builder intentionally uses CPython 3.13. On rolling distributions whose
system Python is 3.14, it uses `uv` to install a private 3.13 interpreter. This
does not replace or modify the system Python. A failed older 3.14 build under
`build-steam/venv` is ignored; corrected builds live under
`build-steam/python313`.

The launch wrapper discovers the bundled Tcl/Tk ELF and script-library paths.
The builder also copies the ABI-matched `libtcl` and `libtk` files from the
isolated Python runtime because Nuitka's Tk plugin currently omits those two
dlopen-loaded libraries on this toolchain.
The release cherry icon is passed to Nuitka as the Linux executable icon,
included as application data for Tk's live window/taskbar icon, and copied to
`steam-depot/CHIPFORGE/assets/chipforge-icon.png` for storefront packaging.
The build finishes by running the frozen application in `--doctor --no-audio`
mode; a broken Tk bundle therefore fails during packaging instead of after upload.

For the actual public build, run the same script inside Valve's current Steam
Linux Runtime developer container, then test the resulting depot on a clean
SteamOS/Ubuntu machine.

## Steamworks setup

1. Replace `YOUR_APP_ID` and `YOUR_DEPOT_ID` in both VDF files.
2. In Installation > General, create a Linux launch option:
   - Executable: `launch.sh`
   - Launch type: Launch (Default)
   - OS: Linux
3. Create a password-protected `alpha` branch.
4. Put the two VDF files in the Steamworks SDK `tools/ContentBuilder/scripts/`.
5. Put or link `steam-depot` as `tools/ContentBuilder/steam-depot`.
6. Upload with SteamCMD:

```bash
steamcmd +login YOUR_STEAM_ACCOUNT +run_app_build ../scripts/app_build_APPID.vdf +quit
```

Never place a Steam password in a script or commit it to the project.

## Data safety

Projects and exports live under `$XDG_DATA_HOME/chipforge`, normally:

```text
~/.local/share/chipforge/projects/
~/.local/share/chipforge/exports/
```

They are outside the Steam depot and survive updates. Steam Cloud can later map
the `projects` directory without syncing large rendered WAV exports.

## Release gate

- Test launch with no Python installed.
- Test PipeWire reconnect after changing the default output device.
- Test suspend/resume and fullscreen on Steam Deck.
- Test 1280x800, 1920x1080 and 2560x1440.
- Confirm state slots 0–9 and chosen-path master WAV export.
- Confirm OSCOPE is the clean default scene and follows the master PCM.
- Cycle all 808 styles; verify Boom/Dust survive state save/load and WAV export.
- Cycle all vaporwave and lo-fi styles; confirm their VAPOR/LO-FI bank buttons
  select matching visual scenes and exported audio stays warm and finite.
- Cycle Vapor Sun, Tape Deck and Rain Glass plus VHS and Rain FX at 1280x800.
- Run AUTO at 4, 8 and 16 bars; confirm changes occur only at pattern boundaries,
  the countdown advances, pause/resume retains position and variation eight
  returns exactly to the primary theme.
- Exercise Flow Lab at minimum/maximum Randomness and Music Math, then blend
  chiptune↔808 and vaporwave↔lo-fi at 25/50/75%; confirm deterministic same-seed rebuilds.
- Toggle 4 CORE / 6 FULL and confirm Perc/Air remain quieter than the core,
  export as stems 5–6, and disappear cleanly when returning to four tracks.
- Load a pre-2.6 four-channel state and confirm it upgrades with empty Perc/Air
  lanes and produces the same four-core master.
- Cycle Split → Deck → Visual at 1280x800 and 1920x1080. Confirm Deck shows all
  four pages in a 2×2 grid, Visual reuses the live visualizer, and F6 swaps them.
- Toggle F11 whole-app fullscreen in all three views. Confirm Escape exits OS
  fullscreen first, then returns Deck/Visual takeover to Split without stopping transport.
- Confirm the cherry-bomb headphones icon appears in the window manager and
  every button shows its bitmap glyph without missing-character squares.
- Confirm the complete Global/Music/Edit/Visual hotkey rail stays visible in
  Split, Deck, Visual and F11 fullscreen at 1280x800.
- Enter Insert mode and verify all 13 piano-row keys—including S, G, H and M—
  enter notes rather than firing their command-mode actions.
- Confirm depot updates do not touch user data.
- Capture real 1920x1080 screenshots from this build.
