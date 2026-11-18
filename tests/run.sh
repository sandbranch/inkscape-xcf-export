#!/bin/sh
# End-to-end test: export each tests/data/*.svg with the extension (in
# the Inkscape Flatpak if installed, else the native Inkscape), load the
# XCF in GIMP 3, and compare GIMP's layers and flattened image with
# Inkscape's own render. Needs gimp-console-3.x and, for isolation,
# gimp-run.sh from github.com/sandbranch/gimp-devtools next to this repo
# (or GIMP_RUN=/path/to/gimp-run.sh).
#
#   tests/run.sh [name...]      default: every tests/data/*.svg
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
work=$here/work
gimp_run=${GIMP_RUN:-$repo/../gimp-devtools/gimp-run.sh}
gimp_console=${GIMP_CONSOLE:-$(command -v gimp-console-3.2 || command -v gimp-console-3.0 || command -v gimp-console)}

rm -rf "$work"
mkdir -p "$work"

if flatpak info org.inkscape.Inkscape >/dev/null 2>&1; then
    ink () { flatpak run --filesystem="$repo" org.inkscape.Inkscape "$@"; }
    ext_python () {
        flatpak run --filesystem="$repo" \
            --env=PYTHONPATH=/app/share/inkscape/extensions \
            --command=python3 org.inkscape.Inkscape "$@"
    }
else
    ink () { inkscape "$@"; }
    ext_python () {
        PYTHONPATH=${INKSCAPE_EXTENSIONS:-/usr/share/inkscape/extensions} python3 "$@"
    }
fi

if [ $# -eq 0 ]; then
    set -- $(cd "$here/data" && ls *.svg | sed 's/\.svg$//')
fi

xcfs=
for name in "$@"; do
    svg=$here/data/$name.svg
    ext_python "$repo/xcf_export.py" --grid=true \
        --output="$work/$name.xcf" "$svg"
    ext_python "$repo/xcf_export.py" --grid=true --linear=true \
        --output="$work/$name-linear.xcf" "$svg"
    ink "$svg" --export-area-page --export-background-opacity=0 \
        --export-filename="$work/$name.ink.png" 2>/dev/null
    python3 "$here/xcf_dump.py" "$work/$name.xcf" > "$work/$name.dump.txt"
    xcfs="$xcfs $work/$name.xcf $work/$name-linear.xcf"
done

# the option switches, on one drawing: name "layers-opts"
if [ -f "$here/data/layers.svg" ]; then
    ext_python "$repo/xcf_export.py" --groups=false --hidden=false \
        --crop=false --background=true --dpi=300 --guides=false \
        --output="$work/layers-opts.xcf" "$here/data/layers.svg"
    xcfs="$xcfs $work/layers-opts.xcf"
    ink "$here/data/layers.svg" --export-area-page --export-dpi=300 \
        --export-background="#ffeedd" --export-background-opacity=1 \
        --export-filename="$work/layers-opts.ink.png" 2>/dev/null
fi

"$gimp_run" --native --home="$work/home" \
    --env=GIMP3_DIRECTORY="$work/home/profile" --env=TEST_XCFS="$xcfs" -- \
    timeout 300 "$gimp_console" --no-interface --no-data --no-fonts --quit \
    --batch-interpreter python-fu-eval \
    -b "exec(open('$here/gimp_check.py').read())" > "$work/gimp.log" 2>&1 || true
grep -q "GIMP CHECK DONE" "$work/gimp.log" || {
    echo "FAIL: GIMP did not finish, see $work/gimp.log"
    exit 1
}

python3 "$here/compare.py" "$work" "$@" layers-opts
