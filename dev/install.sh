#!/bin/sh
# Install the extension for the current user by symlinking it into
# Inkscape's user extensions folder (the Flatpak's, if the Flatpak is
# installed, else ~/.config/inkscape/extensions). --uninstall removes it.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
if [ -n "${INKSCAPE_EXTENSIONS_DIR:-}" ]; then
    dir=$INKSCAPE_EXTENSIONS_DIR
elif flatpak info org.inkscape.Inkscape >/dev/null 2>&1; then
    dir=$HOME/.var/app/org.inkscape.Inkscape/config/inkscape/extensions
else
    dir=${XDG_CONFIG_HOME:-$HOME/.config}/inkscape/extensions
fi
dest=$dir/xcf-export
if [ "${1:-}" = --uninstall ]; then
    rm -rf "$dest"
    echo "removed $dest"
    exit 0
fi
mkdir -p "$dest"
for f in xcf_export.inx xcf_export.py xcf_writer.py css_blend.py; do
    ln -sf "$repo/$f" "$dest/$f"
done
echo "installed into $dest (restart Inkscape)"
