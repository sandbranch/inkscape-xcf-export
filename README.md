# GIMP XCF export for Inkscape, without GIMP

Save an Inkscape drawing as a layered GIMP image: **File > Save As... >
GIMP XCF with layers (\*.xcf)**.

Inkscape's own "GIMP XCF maintaining layers" output drives GIMP through
Script-Fu. It stopped working with GIMP 3, whose Script-Fu no longer has
the GIMP 2 calls it uses ([inkscape/extensions#599]), it has failed on
Windows since 2022 ([#521]), and in the Inkscape Flatpak it is not even
offered, since GIMP is outside the sandbox. This extension writes the
XCF file itself, in Python, so it needs no GIMP at all.

[inkscape/extensions#599]: https://gitlab.com/inkscape/extensions/-/issues/599
[#521]: https://gitlab.com/inkscape/extensions/-/issues/521

## What you get

- Each layer becomes a GIMP layer, cropped to its content and placed
  where it was. Layers with sublayers become **layer groups**. Objects
  outside any layer get a layer of their own.
- **Visibility, opacity and blend mode** stay layer properties in GIMP,
  not baked into the pixels. Hidden layers come along, still hidden.
- It **looks the same** in GIMP: layers blend in sRGB as Inkscape draws
  them (checked pixel by pixel, see Tests). CSS blend modes with a GIMP
  equivalent (multiply, screen, overlay, darken, lighten, hard light,
  difference, exclusion) become that GIMP mode. The seven that GIMP
  computes differently (color dodge, color burn, soft light, hue,
  saturation, color, luminosity) are baked: blended with what lies below
  them, by the W3C formulas, into a Normal layer. Or keep the nearest
  GIMP mode instead, which stays editable but looks different.
- **Guides**, the **grid**, the **resolution** and the document unit.
- An optional bottom layer with the page colour.
- A layer with a filter, clip or mask that also has sublayers is
  rendered as one layer, since GIMP has no group-level equivalent.

Options: resolution, sublayers as groups, crop, hidden layers,
background, guides, grid, blend modes GIMP lacks, and "blend in linear
light" for GIMP's own default compositing.

Tested with Inkscape 1.4.4 (Flatpak) and GIMP 3.2.8. It writes XCF
version 10, which GIMP 2.10 introduced, so GIMP 2.10 should read it too,
but that is not tested yet; neither are older Inkscape versions or
Windows. Needs numpy and Pillow (the Inkscape Flatpak has both).

## Install

    dev/install.sh            # symlinks into your Inkscape extensions folder
    dev/install.sh --uninstall

It finds the Flatpak's folder
(`~/.var/app/org.inkscape.Inkscape/config/inkscape/extensions`) or the
native one (`~/.config/inkscape/extensions`); set
`INKSCAPE_EXTENSIONS_DIR` for another. Or copy `xcf_export.inx`,
`xcf_export.py`, `xcf_writer.py` and `css_blend.py` there by hand. Restart Inkscape.

From the command line:

    inkscape drawing.svg --export-extension=org.sandbranch.output.xcf \
        --export-filename=drawing.xcf

## Known differences

- With "Add page colour as background layer", a blend-mode layer
  in GIMP also blends with the background layer. Inkscape draws the page
  colour under the finished drawing, so there it does not.
- 8-bit only, like Inkscape's PNG export by default.
- Only the first page of a multi-page document; a layer whose content
  is only on other pages is left out.
- An old-style grid such as `spacingx="5mm"` is saved the way Inkscape
  1.4 draws it, which in a document with a scaled viewBox is not 5 mm
  (Inkscape uses the length in CSS pixels as user units).
- When nothing is visible, the export stops with a message, but
  Inkscape's extension machinery may leave an empty file behind.

## Tests

Unit tests, no Inkscape or GIMP needed (numpy and pytest; also run on
GitHub Actions with `ruff format --check`):

    python3 -m pytest tests/

They check the writer (tiles across 64-pixel edges, dummy levels, layer
group paths, properties, guides) by reading its files back with
`tests/xcf_dump.py`, and they first check that reader against
`tests/data/gimp-reference.xcf`, a file GIMP 3.2.8 saved itself with
known pixels (made by `tests/make_gimp_reference.sh`). The CSS blend
maths is checked against values worked out by hand from the W3C
formulas.

End to end, with Inkscape and GIMP 3:

    tests/run.sh

Exports every `tests/data/*.svg` (layers and groups, all 15 blend modes,
filters, clips and clones, blend modes inside isolated groups, two
pages, a bitmap and text, an old-style grid), plus variants: all option
switches at 300 dpi, linear light, GIMP's nearest blend modes (which
must warn), the export through Inkscape's own `.inx` with a throwaway
profile, and a drawing with nothing visible (which must stop with a
message). It loads each XCF in GIMP 3 headless and checks GIMP's layer
tree, guides and grid against `tests/data/*.expect.json`, and GIMP's
flattened image against Inkscape's own PNG export, premultiplied: a
file passes when the mean difference is under 0.5 of 255 and at most
0.5 % of the pixels differ by more than 8. Needs `gimp-console-3.x` and
[gimp-devtools](https://github.com/sandbranch/gimp-devtools) next to
this repo (for `gimp-run.sh`, which keeps the test GIMP away from your
own profile).

Not tested yet: the options dialog itself, GIMP 2.10, Inkscape before
1.4.4, Windows and macOS.

## How

`xcf_writer.py` is a small standalone XCF writer (numpy and zlib):
version 10, 8-bit sRGB, zlib-compressed 64x64 tiles, layer groups via
item paths, following GIMP's `app/xcf/xcf-save.c` and the XCF format
description. `xcf_export.py` plans the layer tree, renders every layer
in a single Inkscape run with all layer opacity, visibility and blend
removed, and writes them out.

## Licence

GPL-2.0-or-later, like the Inkscape extension it replaces (whose option
set and some code it started from). See `COPYING`.
