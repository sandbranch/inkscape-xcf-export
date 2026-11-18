#!/bin/sh
# Record the Inkscape calls and expected outputs for the upstream tests
# (tests/test_gimp_xcf.py in an inkscape/extensions checkout made with
# make-upstream.py), using the Inkscape Flatpak, or a native inkscape if
# no Flatpak is installed. Needs the checkout's .venv with its test
# dependencies.
#
#   dev/record-upstream-mocks.sh ../inkscape-extensions
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu
target=$(cd "$1" && pwd)
work=${XDG_CACHE_HOME:-$HOME/.cache}/xcf-export-record
rm -rf "$work"
mkdir -p "$work/bin" "$work/tmp"
if flatpak info org.inkscape.Inkscape >/dev/null 2>&1; then
    # the Flatpak cannot see the host /tmp, so temp files go under $work
    cat > "$work/bin/inkscape" <<WRAP
#!/bin/sh
exec flatpak run --filesystem="$work/tmp" org.inkscape.Inkscape "\$@"
WRAP
    chmod +x "$work/bin/inkscape"
    PATH=$work/bin:$PATH
fi
cd "$target"
# Drop the old recordings of this test, then follow upstream's workflow:
# 1. call the real Inkscape; each call is saved as <key>.msg.output (the
#    run reports failures because the mock prints where it saved them);
# 2. keep those recordings as <key>.msg;
# 3. replay them and write the expected outputs (data/refs);
# 4. replay once more as CI does, which must pass.
rm -f tests/data/refs/gimp_xcf*.out tests/data/cmd/inkscape/*.msg.output
rm -rf tests/data/cmd/gimp
TMPDIR=$work/tmp NO_MOCK_COMMANDS=1 \
    .venv/bin/python -m pytest -q tests/test_gimp_xcf.py >"$work/record.log" 2>&1 || true
recorded=0
for f in tests/data/cmd/inkscape/*.msg.output; do
    [ -e "$f" ] || continue
    mv "$f" "${f%.output}"
    recorded=$((recorded + 1))
done
echo "recorded $recorded Inkscape calls"
EXPORT_COMPARE=3 .venv/bin/python -m pytest -q tests/test_gimp_xcf.py >"$work/refs.log" 2>&1 || true
.venv/bin/python -m pytest -q tests/test_gimp_xcf.py tests/test_xcf_writer.py
