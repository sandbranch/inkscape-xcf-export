#!/bin/sh
# Regenerate tests/data/gimp-reference.xcf with GIMP 3 (see
# make_gimp_reference.py). Needs gimp-console-3.x and gimp-devtools'
# gimp-run.sh next to this repo, like run.sh.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
gimp_run=${GIMP_RUN:-$repo/../gimp-devtools/gimp-run.sh}
gimp_console=${GIMP_CONSOLE:-$(command -v gimp-console-3.2 || command -v gimp-console-3.0 || command -v gimp-console)}
home=$here/work/refhome
mkdir -p "$home"
"$gimp_run" --home="$home" --env=GIMP3_DIRECTORY="$home/profile" \
    --env=TEST_OUT="$here/data/gimp-reference.xcf" -- \
    timeout 120 "$gimp_console" --no-interface --no-data --no-fonts --quit \
    --batch-interpreter python-fu-eval \
    -b "exec(open('$here/make_gimp_reference.py').read())" 2>&1 | grep "REFERENCE SAVED"
"$gimp_console" --version
