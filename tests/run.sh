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
    ink_profile () {
        flatpak run --filesystem="$repo" --env=INKSCAPE_PROFILE_DIR="$INKSCAPE_PROFILE_DIR" \
            org.inkscape.Inkscape "$@"
    }
    ext_python () {
        flatpak run --filesystem="$repo" \
            --env=PYTHONPATH=/app/share/inkscape/extensions \
            --command=python3 org.inkscape.Inkscape "$@"
    }
else
    ink () { inkscape "$@"; }
    ink_profile () { inkscape "$@"; }
    ext_python () {
        PYTHONPATH=${INKSCAPE_EXTENSIONS:-/usr/share/inkscape/extensions} python3 "$@"
    }
fi

if [ $# -eq 0 ]; then
    set -- $(cd "$here/data" && ls *.svg | sed 's/\.svg$//' | grep -v '^empty$')
fi

status=0
xcfs=
variants=
add () { xcfs="$xcfs $work/$1.xcf"; variants="$variants $1"; }

for name in "$@"; do
    svg=$here/data/$name.svg
    ext_python "$repo/xcf_export.py" --grid=true \
        --output="$work/$name.xcf" "$svg"
    ext_python "$repo/xcf_export.py" --grid=true --linear=true \
        --output="$work/$name-linear.xcf" "$svg"
    ink "$svg" --export-area-page --export-background-opacity=0 \
        --export-filename="$work/$name.ink.png" 2>/dev/null
    python3 "$here/xcf_dump.py" "$work/$name.xcf" > "$work/$name.dump.txt"
    add "$name"
    add "$name-linear"
done

# the option switches, on one drawing: name "layers-opts"
if [ -f "$here/data/layers.svg" ]; then
    ext_python "$repo/xcf_export.py" --groups=false --hidden=false \
        --crop=false --background=true --dpi=300 --guides=false \
        --output="$work/layers-opts.xcf" "$here/data/layers.svg"
    add layers-opts
    ink "$here/data/layers.svg" --export-area-page --export-dpi=300 \
        --export-background="#ffeedd" --export-background-opacity=1 \
        --export-filename="$work/layers-opts.ink.png" 2>/dev/null
fi

# blend modes GIMP lacks, kept as GIMP's nearest modes: name "blend-gimp"
if [ -f "$here/data/blend.svg" ]; then
    ext_python "$repo/xcf_export.py" --blend=gimp \
        --output="$work/blend-gimp.xcf" "$here/data/blend.svg" \
        2>"$work/blend-gimp.err"
    if grep -q "no exact match" "$work/blend-gimp.err"; then
        echo "ok   blend-gimp warns about the approximate layers"
    else
        echo "FAIL blend-gimp: no warning about approximate blend modes"
        status=1
    fi
    add blend-gimp
fi

# through Inkscape's own extension machinery (the .inx), with a throwaway
# Inkscape profile so the user's own extensions are not involved
profile=$work/inkscape-profile
mkdir -p "$profile/extensions/xcf-export"
for f in xcf_export.inx xcf_export.py xcf_writer.py css_blend.py; do
    ln -sf "$repo/$f" "$profile/extensions/xcf-export/$f"
done
if INKSCAPE_PROFILE_DIR=$profile ink_profile "$here/data/layers.svg" \
        --export-extension=org.sandbranch.output.xcf \
        --export-filename="$work/layers-ext.xcf" >"$work/layers-ext.log" 2>&1 \
        && [ -s "$work/layers-ext.xcf" ]; then
    add layers-ext
else
    echo "FAIL layers-ext: Inkscape did not export through the .inx, see $work/layers-ext.log"
    status=1
fi

# nothing visible: must stop with a message and a failure status
if ext_python "$repo/xcf_export.py" --output="$work/empty.xcf" \
        "$here/data/empty.svg" 2>"$work/empty.err"; then
    echo "FAIL empty: exported although nothing is visible"
    status=1
elif grep -q "nothing visible" "$work/empty.err"; then
    echo "ok   empty stops with a message"
else
    echo "FAIL empty: failed without the expected message, see $work/empty.err"
    status=1
fi

"$gimp_run" --home="$work/home" \
    --env=GIMP3_DIRECTORY="$work/home/profile" --env=TEST_XCFS="$xcfs" -- \
    timeout 300 "$gimp_console" --no-interface --no-data --no-fonts --quit \
    --batch-interpreter python-fu-eval \
    -b "exec(open('$here/gimp_check.py').read())" > "$work/gimp.log" 2>&1 || true
grep -q "GIMP CHECK DONE" "$work/gimp.log" || {
    echo "FAIL: GIMP did not finish, see $work/gimp.log"
    exit 1
}

python3 "$here/compare.py" "$work" $variants || status=1
exit $status
