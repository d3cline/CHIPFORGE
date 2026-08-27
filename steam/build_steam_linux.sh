#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
build_root="${project_root}/build-steam"
depot_root="${project_root}/steam-depot"

# Nuitka's CPython 3.14 support is still experimental and currently breaks on
# Arch's GC headers. Use a private 3.13 toolchain regardless of system default.
if [[ -n "${PYTHON:-}" ]]; then
  python_bin="${PYTHON}"
elif command -v python3.13 >/dev/null 2>&1; then
  python_bin="$(command -v python3.13)"
elif command -v uv >/dev/null 2>&1; then
  echo "CHIPFORGE: preparing isolated CPython 3.13 with uv"
  uv python install 3.13
  python_bin="$(uv python find 3.13)"
else
  echo "CHIPFORGE needs Python 3.13 for the Steam compiler." >&2
  echo "Arch/Manjaro: sudo pacman -S uv" >&2
  echo "Then rerun this script; it will install an isolated Python 3.13." >&2
  exit 2
fi

python_version="$("${python_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${python_version}" != "3.13" ]]; then
  echo "CHIPFORGE Steam builds require Python 3.13; selected ${python_bin} is ${python_version}." >&2
  echo "Install uv and rerun without PYTHON, or set PYTHON to a 3.13 executable." >&2
  exit 2
fi

toolchain_root="${build_root}/python313"
venv_root="${toolchain_root}/venv"

command -v pkg-config >/dev/null
pkg-config --exists libpipewire-0.3
echo "CHIPFORGE: building with $("${python_bin}" --version)"
"${python_bin}" -m venv "${venv_root}"
"${venv_root}/bin/python" -m pip install --upgrade pip
"${venv_root}/bin/python" -m pip install -r "${project_root}/requirements.txt" 'nuitka>=4.1,<5' ordered-set zstandard

cc -O2 -pipe -fPIE -pie -Wall -Wextra -Werror \
  "${project_root}/native/pipewire_sink.c" -o "${project_root}/chipforge-pw-sink" \
  $(pkg-config --cflags --libs libpipewire-0.3) -pthread

"${venv_root}/bin/python" -m nuitka \
  --mode=standalone --enable-plugin=tk-inter --assume-yes-for-downloads \
  --linux-icon="${project_root}/assets/chipforge-icon.png" \
  --include-data-files="${project_root}/assets/chipforge-icon.png=assets/chipforge-icon.png" \
  --output-dir="${toolchain_root}" --output-filename=chipforge-workstation \
  "${project_root}/chipforge_workstation.py"

mkdir -p "${depot_root}/CHIPFORGE"
cp -a "${toolchain_root}/chipforge_workstation.dist/." "${depot_root}/CHIPFORGE/"
cp "${project_root}/chipforge-pw-sink" "${depot_root}/CHIPFORGE/"
cp "${project_root}/steam/launch.sh" "${depot_root}/CHIPFORGE/"
cp "${project_root}/LICENSE" "${depot_root}/CHIPFORGE/"
mkdir -p "${depot_root}/CHIPFORGE/assets"
cp "${project_root}/assets/chipforge-icon.png" "${depot_root}/CHIPFORGE/assets/"

# Nuitka includes _tkinter plus the Tcl/Tk scripts from python-build-standalone,
# but currently misses its dlopen'd libtcl/libtk ELF files. Copy the exact ABI-
# matched libraries from the uv-managed interpreter used for this build.
python_runtime_root="$("${python_bin}" -c 'import sys; print(sys.prefix)')"
mapfile -t tk_runtime_libraries < <(
  find "${python_runtime_root}" \( -type f -o -type l \) \
    \( -name 'libtcl*.so*' -o -name 'libtk*.so*' \) -print
)
if [[ "${#tk_runtime_libraries[@]}" -eq 0 ]]; then
  echo "CHIPFORGE: no Tcl/Tk shared libraries found under ${python_runtime_root}" >&2
  exit 3
fi
for runtime_library in "${tk_runtime_libraries[@]}"; do
  cp -Lv "${runtime_library}" "${depot_root}/CHIPFORGE/$(basename "${runtime_library}")"
done

chmod +x "${depot_root}/CHIPFORGE/launch.sh" "${depot_root}/CHIPFORGE/chipforge-workstation" "${depot_root}/CHIPFORGE/chipforge-pw-sink"
echo "CHIPFORGE: verifying frozen Tcl/Tk runtime"
"${depot_root}/CHIPFORGE/launch.sh" --doctor --no-audio
echo "Steam depot ready: ${depot_root}/CHIPFORGE"
