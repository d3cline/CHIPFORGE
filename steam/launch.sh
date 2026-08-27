#!/usr/bin/env bash
set -euo pipefail
game_dir="$(cd "$(dirname "$0")" && pwd)"
export XDG_DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
export TK_SILENCE_DEPRECATION=1

# Python-build-standalone/Nuitka keeps Tcl and Tk shared libraries beside their
# script trees. _tkinter loads them by basename, so expose every actual bundled
# library directory instead of assuming one Nuitka layout.
runtime_library_path="${game_dir}"
while IFS= read -r library_file; do
  library_dir="${library_file%/*}"
  case ":${runtime_library_path}:" in
    *":${library_dir}:"*) ;;
    *) runtime_library_path="${runtime_library_path}:${library_dir}" ;;
  esac
done < <(find "${game_dir}" \( -type f -o -type l \) \( -name 'libtcl*.so*' -o -name 'libtk*.so*' \) -print)
export LD_LIBRARY_PATH="${runtime_library_path}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

# Point Tcl/Tk at the bundled script libraries as well. This prevents the next
# class of failure after the ELF loader finds libtcl/libtk successfully.
tcl_init="$(find "${game_dir}" -type f -name init.tcl -print -quit)"
tk_init="$(find "${game_dir}" -type f -name tk.tcl -print -quit)"
[[ -z "${tcl_init}" ]] || export TCL_LIBRARY="${tcl_init%/*}"
[[ -z "${tk_init}" ]] || export TK_LIBRARY="${tk_init%/*}"

cd "${game_dir}"
exec "${game_dir}/chipforge-workstation" "$@"
