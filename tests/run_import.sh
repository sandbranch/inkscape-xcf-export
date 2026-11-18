#!/bin/sh
# End-to-end test of the XCF import: GIMP 3 makes test files in every
# precision and colour mode, with the pixels of each layer as GIMP
# decodes them; our reader must match those (check_reader.py), and
# Inkscape's render of each file opened through xcf_import must match the
# layers stacked as SVG stacks them (check_import.py). The extension must
# be installed (dev/install.sh); needs gimp-console-3.x, inkscape and
# gimp-devtools' gimp-run.sh next to this repo (or GIMP_RUN).
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
work=$here/work-import
gimp_run=${GIMP_RUN:-$repo/../gimp-devtools/gimp-run.sh}
gimp_console=${GIMP_CONSOLE:-$(command -v gimp-console-3.2 || command -v gimp-console-3.0 || command -v gimp-console)}
rm -rf "$work"
mkdir -p "$work"
"$gimp_run" --native --home="$work/home" --env=GIMP3_DIRECTORY="$work/home/profile" \
    --env=TEST_OUT="$work" -- timeout 300 "$gimp_console" --no-interface --no-data \
    --no-fonts --quit --batch-interpreter python-fu-eval \
    -b "exec(open('$here/gimp_make_xcfs.py').read())" > "$work/gimp.log" 2>&1 || true
grep -q "XCFS MADE" "$work/gimp.log" || { echo "FAIL: GIMP made no test files, see $work/gimp.log"; exit 1; }
status=0
python3 "$here/check_reader.py" "$work" || status=1
for xcf in "$work"/*.xcf; do
    inkscape "$xcf" --export-type=png --export-area-page --export-dpi=300 \
        --export-background-opacity=0 --export-filename="${xcf%.xcf}.ink.png" 2>/dev/null || true
done
python3 "$here/check_import.py" "$work" || status=1
exit $status
